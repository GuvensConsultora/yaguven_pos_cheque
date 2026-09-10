import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Cuentas de cuenta corriente, para encontrar la linea a cancelar.
CC = ('asset_receivable', 'liability_payable')


class PosSession(models.Model):
    _inherit = 'pos.session'

    @api.model
    def _load_pos_data_models(self, config):
        """Suma `res.bank` a los modelos que el POS baja al abrir la sesión.

        El core trae 45 modelos y `res.bank` no está (verificado en
        `point_of_sale/models/pos_session.py:139` de esta instancia): al POS
        nativo no le hace falta un banco para vender. Acá sí, para que el banco
        del cheque salga de un desplegable y no de un campo de texto.

        Se suma al final y sin quitar nada: la lista del core se respeta.
        """
        return super()._load_pos_data_models(config) + ['res.bank']

    # ══════════════════════════════════════════════════════════════════════
    #  El cheque en cartera
    # ══════════════════════════════════════════════════════════════════════
    def _validate_session(self, balancing_account=False, amount_to_balance=0,
                          bank_payment_method_diffs=None):
        """Al cerrar la caja, cada cobro con cheque se convierte en un pago real.

        POR QUE ACA Y NO ANTES: `l10n_latam.check.payment_id` es obligatorio —un
        cheque no existe sin un `account.payment`— y el pago tiene que cancelar
        algo que ya exista. Recien despues del cierre estan las lineas de cuenta
        a cobrar que dejo el POS.

        POR QUE NO SE USA EL DIARIO DEL MEDIO DE PAGO, que seria lo obvio:

          diario de EFECTIVO -> el POS mete los cheques en el ARQUEO DE CAJA y el
                                cajero tendria que contarlos como billetes;
          diario de BANCO    -> el POS si crea un pago por cobro, pero la
                                localizacion NO admite ahi el metodo
                                `new_third_party_checks` (aplica solo a `cash`),
                                asi que el cheque queda FUERA del circuito: no se
                                puede depositar, endosar ni marcar rechazado.

        Por eso el medio va SIN diario (`pay_later`): el cobro queda en la cuenta
        del cliente, y el pago que se crea aca —en el diario de cheques de
        terceros de la localizacion, con su metodo— la cancela. No duplica: mueve.
        """
        res = super()._validate_session(
            balancing_account=balancing_account,
            amount_to_balance=amount_to_balance,
            bank_payment_method_diffs=bank_payment_method_diffs)
        try:
            self._yg_materializar_cheques()
        except Exception as e:
            # El cierre de caja NO se cae por esto: la sesion ya esta cerrada y
            # la plata contabilizada. Queda el aviso en el chatter de la sesion
            # para que administracion lo resuelva.
            _logger.exception('yaguven_pos_cheque: no se pudieron materializar '
                              'los cheques de la sesion %s', self.name)
            self.message_post(body=_(
                'No se pudieron registrar los cheques de esta sesión: %(err)s\n\n'
                'La caja cerró bien y la plata está contabilizada; lo que falta '
                'es la ficha de cada cheque en cartera.', err=str(e)[:300]))
        return res

    def _yg_materializar_cheques(self):
        """Un `account.payment` con su cheque por cada cobro con cheque."""
        cobros = self.order_ids.payment_ids.filtered(
            lambda p: p.is_check and p.amount)
        for cobro in cobros:
            if self._yg_ya_registrado(cobro):
                continue
            self._yg_crear_pago(cobro)

    def _yg_ya_registrado(self, cobro):
        Cheque = self.env.get('l10n_latam.check')
        if Cheque is None:
            return False
        return bool(Cheque.sudo().search_count([
            ('name', '=', cobro.check_number),
            ('bank_id', '=', cobro.check_bank_id.id)]))

    def _yg_crear_pago(self, cobro):
        """El pago que cancela la cuenta a cobrar y deja el cheque en cartera.

        EL CHEQUE VA DENTRO DEL PAGO, no se crea aparte. La localizacion valida
        al postear que el importe del pago coincida con el del cheque asociado:
        creando el cheque despues, el pago se postea sin cheque y falla con
        «The amount of the payment does not match the amount of the selected
        check». Medido el 10/09. Con `l10n_latam_new_check_ids` en el mismo
        `create` queda todo consistente y es el camino nativo.
        """
        metodo = cobro.payment_method_id
        diario = metodo.journal_id
        linea = diario.inbound_payment_method_line_ids.filtered(
            lambda l: l.code == 'new_third_party_checks')[:1]
        if not diario or not linea:
            raise UserError(_(
                'El medio «%(medio)s» no tiene un diario de cheques de terceros '
                'con el método «Cheques de terceros nuevos» habilitado.',
                medio=metodo.display_name))

        cheque = {
            'name': cobro.check_number,
            'bank_id': cobro.check_bank_id.id,
            'issuer_vat': cobro.check_issuer_vat,
            'payment_date': cobro.check_payment_date,
            'amount': cobro.amount,
            'at_sight': cobro.check_type == 'at_sight',
            'is_cpd': cobro.check_type == 'cpd',
            'is_echeq': cobro.check_type == 'echeq',
        }
        if cobro.check_issue_date:
            cheque['issue_date'] = cobro.check_issue_date

        pago = self.env['account.payment'].sudo().create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': cobro.pos_order_id.partner_id.id,
            'amount': cobro.amount,
            'date': (self.stop_at and self.stop_at.date()) or fields.Date.today(),
            'journal_id': diario.id,
            'payment_method_line_id': linea.id,
            'memo': _('Cheque %(nro)s · %(orden)s',
                      nro=cobro.check_number, orden=cobro.pos_order_id.name),
            'pos_session_id': self.id,
            'l10n_latam_new_check_ids': [(0, 0, cheque)],
        })
        pago.action_post()
        self._yg_conciliar(pago, cobro)
        return pago

    def _yg_conciliar(self, pago, cobro):
        """Aparea el pago con la linea de cuenta a cobrar que dejo el POS.

        Si no aparea, el cheque igual queda registrado: lo que falta es el
        apareo, y eso se resuelve a mano sin perder el dato.
        """
        partner = cobro.pos_order_id.partner_id
        if not partner:
            return
        dominio = [('move_id', '=', self.move_id.id),
                   ('partner_id', '=', partner.id),
                   ('account_id.account_type', 'in', list(CC)),
                   ('reconciled', '=', False)]
        cand = self.env['account.move.line'].sudo().search(dominio)
        cand = cand.filtered(
            lambda l: abs(abs(l.balance) - cobro.amount) < 0.01)[:1]
        if not cand:
            return
        linea_pago = pago.move_id.line_ids.filtered(
            lambda l: l.account_id.account_type in CC)[:1]
        if linea_pago:
            (cand + linea_pago).reconcile()

    # ══════════════════════════════════════════════════════════════════════
    def _yg_check_config(self):
        """El medio de cheque va con el diario de cheques de terceros.

        Tiene que ser de tipo EFECTIVO: es el único donde la localización admite
        el método «Cheques de terceros nuevos», que es el que después permite
        depositar, endosar o marcar rechazado. Que sea de efectivo no lo mete en
        el arqueo de billetes: eso lo resuelve `_compute_is_cash_count`.

        Se verifica al ABRIR la sesión: si falta la configuración, el cajero se
        entera antes de vender y no después de cobrar veinte cheques.
        """
        for sesion in self:
            malos = []
            for m in sesion.config_id.payment_method_ids.filtered('is_check'):
                falta = []
                if not m.journal_id:
                    falta.append('le falta el diario de cheques de terceros')
                elif m.journal_id.type != 'cash':
                    falta.append('el diario tiene que ser de tipo efectivo')
                elif not m.journal_id.inbound_payment_method_line_ids.filtered(
                        lambda l: l.code == 'new_third_party_checks'):
                    falta.append('el diario no tiene habilitado «Cheques de '
                                 'terceros nuevos»')
                if not m.split_transactions:
                    falta.append('le falta «Identificar al cliente»')
                if falta:
                    malos.append(f"{m.display_name} ({', '.join(falta)})")
            if malos:
                raise UserError(_(
                    'Estos medios de pago están marcados como cheque pero les '
                    'falta configuración:\n\n%(medios)s',
                    medios='\n'.join('· ' + x for x in malos)))

    def action_pos_session_open(self):
        self._yg_check_config()
        return super().action_pos_session_open()
