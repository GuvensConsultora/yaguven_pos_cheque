import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Cuentas de cuenta corriente, para encontrar la linea a cancelar.
CC = ('asset_receivable', 'liability_payable')


class PosSession(models.Model):
    _inherit = 'pos.session'

    # ══════════════════════════════════════════════════════════════════════
    #  El cheque en cartera
    # ══════════════════════════════════════════════════════════════════════
    def _validate_session_accounting(self):
        """Al cerrar la caja, cada cobro con cheque se convierte en un pago real.

        Odoo 20: el cierre pasa por `_validate_session_accounting` (en 19 era
        `_validate_session`, que ya no existe).

        El medio de cheque es «Cuenta de cliente» (`pay_later`, sin diario): en 20
        cada caja admite un solo medio de efectivo, y el diario de cheques de
        terceros es de efectivo. Además, en 20 toda venta con `pay_later` se
        factura sí o sí, así que el cobro queda ABIERTO en la factura del cliente.
        Acá se crea el pago en el diario de cheques de terceros (el del campo
        `check_journal_id` del medio), con el cheque adentro, y se concilia contra
        esa factura. No duplica: mueve la deuda del cliente al cheque en cartera.
        """
        res = super()._validate_session_accounting()
        try:
            with self.env.cr.savepoint():
                self._yg_materializar_cheques()
        except Exception as e:
            # El cierre de caja NO se cae por esto: la venta está facturada y la
            # deuda del cliente registrada. Queda el aviso en el chatter de la
            # sesión para que administración cargue el cheque a mano.
            _logger.exception('yaguven_pos_cheque: no se pudieron materializar '
                              'los cheques de la sesion %s', self.name)
            self.message_post(body=_(
                'No se pudieron registrar los cheques de esta sesión: %(err)s\n\n'
                'La caja cerró bien y las ventas quedaron facturadas; lo que falta '
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
        norm = lambda v: " ".join((v or "").lower().split())
        cheques = self.env['l10n_latam.check'].sudo().search([('name', '=', cobro.check_number)])
        return bool(cheques.filtered(
            lambda c: norm(c.yaguven_bank_display) == norm(cobro.check_bank_name)))

    def _yg_crear_pago(self, cobro, partner=None, memo=None, conciliar=True):
        """El pago que cancela la cuenta a cobrar y deja el cheque en cartera.

        EL CHEQUE VA DENTRO DEL PAGO, no se crea aparte. La localizacion valida
        al postear que el importe del pago coincida con el del cheque asociado:
        creando el cheque despues, el pago se postea sin cheque y falla con
        «The amount of the payment does not match the amount of the selected
        check». Medido el 10/09. Con `l10n_latam_new_check_ids` en el mismo
        `create` queda todo consistente y es el camino nativo.

        `partner` / `memo` / `conciliar`: la liquidación de facturas desde el POS
        (`yaguven_pos_cheque_settle`) cobra sin orden del POS; pasa el cliente de
        las facturas y concilia ella misma contra esas facturas.
        """
        metodo = cobro.payment_method_id
        diario = metodo.check_journal_id
        linea = diario.inbound_payment_method_line_ids.filtered(
            lambda l: l.code == 'new_third_party_checks')[:1]
        if not diario or not linea:
            raise UserError(_(
                'El medio «%(medio)s» no tiene un diario de cheques de terceros '
                'con el método «Cheques de terceros nuevos» habilitado.',
                medio=metodo.display_name))

        cheque = {
            'name': cobro.check_number,
            'yaguven_bank_name': cobro.check_bank_name,
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
            'partner_id': (partner or cobro.pos_order_id.partner_id).id,
            'amount': cobro.amount,
            'date': (self.stop_at and self.stop_at.date()) or fields.Date.today(),
            'journal_id': diario.id,
            'payment_method_line_id': linea.id,
            'memo': memo or _('Cheque %(nro)s · %(orden)s',
                              nro=cobro.check_number, orden=cobro.pos_order_id.name),
            'pos_session_id': self.id,
            'l10n_latam_new_check_ids': [(0, 0, cheque)],
        })
        pago.action_post()
        if conciliar:
            self._yg_conciliar(pago, cobro)
        return pago

    def _yg_conciliar(self, pago, cobro):
        """Aparea el pago con la cuenta a cobrar de la FACTURA de la venta.

        Odoo 20: la sesión ya no tiene un asiento único (`move_id`); una venta con
        «Cuenta de cliente» se factura sí o sí y su deuda queda en esa factura.
        Si no aparea, el cheque igual queda registrado: falta el apareo, que se
        resuelve a mano sin perder el dato.
        """
        factura = cobro.pos_order_id.account_move
        partner = cobro.pos_order_id.partner_id.commercial_partner_id
        if not factura or not partner:
            return
        cand = factura.line_ids.filtered(
            lambda l: l.account_id.account_type in CC
            and l.partner_id.commercial_partner_id == partner
            and not l.reconciled)
        linea_pago = pago.move_id.line_ids.filtered(
            lambda l: l.account_id.account_type in CC and not l.reconciled)[:1]
        if cand and linea_pago and cand[:1].account_id == linea_pago.account_id:
            (cand[:1] + linea_pago).reconcile()

    # ══════════════════════════════════════════════════════════════════════
    def _yg_check_config(self):
        """El medio de cheque tiene que estar bien armado antes de vender.

        En 20: medio «Cuenta de cliente» (`pay_later`, sin diario propio) + el
        diario de cheques de terceros en `check_journal_id` (de efectivo, con el
        método «Cheques de terceros nuevos»). Se verifica al ABRIR la caja: si
        falta algo, el cajero se entera antes de cobrar el primer cheque.
        """
        for sesion in self:
            malos = []
            for m in sesion.config_id.payment_method_ids.filtered('is_check'):
                falta = m._yg_faltantes_cheque()
                if falta:
                    malos.append(f"{m.display_name} ({', '.join(falta)})")
            if malos:
                raise UserError(_(
                    'Estos medios de pago están marcados como cheque pero les '
                    'falta configuración:\n\n%(medios)s',
                    medios='\n'.join('· ' + x for x in malos)))

    def _set_opening_control_data(self, cashbox_value, notes):
        # 20: la apertura pasa por acá (action_pos_session_open ya no existe).
        self._yg_check_config()
        return super()._set_opening_control_data(cashbox_value, notes)
