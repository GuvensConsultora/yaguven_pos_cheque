from odoo import _, api, models
from odoo.exceptions import UserError


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
    def _create_split_account_payments(self, payment_amounts_list):
        """Cuelga la ficha del cheque del `account.payment` que crea el POS.

        NO se crea un pago aparte, y es la decisión central de este módulo. El
        POS ya crea un `account.payment` por cobro al cerrar la sesión (este
        mismo método del core, `pos_session.py:1228`), y el asiento de cierre ya
        deja la plata en la cuenta del diario del medio de pago. Un
        `account.payment` propio ADEMAS de ése haría entrar el importe DOS
        VECES, y el descalce aparecería recién en el balance.

        `l10n_latam.check.payment_id` es obligatorio: un cheque no puede existir
        suelto. Por eso la ficha se cuelga acá y no antes — antes no hay pago
        del cual colgarla.

        Requiere que el medio de pago tenga diario y `split_transactions`
        (ver `_yg_check_config`): sin `split_transactions` el core agrupa todos
        los cobros del método en UN pago (`_create_combine_account_payment`) y
        no hay a qué cheque corresponde cada uno.
        """
        res = super()._create_split_account_payments(payment_amounts_list)

        # Si la localización no está instalada, este módulo igual sirve: los
        # datos del cheque quedan guardados en la línea de pago. Lo que no hay
        # es ficha en cartera. Por eso no se declara la dependencia dura.
        if 'l10n_latam.check' not in self.env:
            return res

        for pos_payment, linea in res.items():
            if not pos_payment.is_check or not linea:
                continue
            pago = self.env['account.payment'].search(
                [('move_id', '=', linea.move_id.id)], limit=1)
            if not pago:
                continue
            self._yg_crear_cheque(pos_payment, pago)
        return res

    def _yg_crear_cheque(self, pos_payment, pago):
        """Crea el `l10n_latam.check` de un cobro del POS.

        Dedupe por (número, banco, pago): si la sesión se reprocesa, no se
        duplica la ficha. La clave incluye el banco porque dos bancos distintos
        emiten el mismo número de cheque.
        """
        Cheque = self.env['l10n_latam.check'].sudo()
        dominio = [
            ('name', '=', pos_payment.check_number),
            ('bank_id', '=', pos_payment.check_bank_id.id),
            ('payment_id', '=', pago.id),
        ]
        if Cheque.search_count(dominio):
            return Cheque.browse()

        vals = {
            'name': pos_payment.check_number,
            'bank_id': pos_payment.check_bank_id.id,
            'issuer_vat': pos_payment.check_issuer_vat,
            'payment_date': pos_payment.check_payment_date,
            'payment_id': pago.id,
        }
        # Los opcionales sólo si vienen: escribir False sobre un campo que la
        # localización calcula sola es peor que no tocarlo.
        if pos_payment.check_issue_date:
            vals['issue_date'] = pos_payment.check_issue_date
        if pos_payment.check_is_echeq:
            vals['is_echeq'] = True
        return Cheque.create(vals)

    # ══════════════════════════════════════════════════════════════════════
    def _yg_check_config(self):
        """Los medios de cheque necesitan diario y `split_transactions`.

        Se verifica al ABRIR la sesión y no al cerrarla: si falta la
        configuración, el cajero se entera antes de vender, no después de
        cobrar veinte cheques que no se van a poder registrar.
        """
        for sesion in self:
            malos = sesion.config_id.payment_method_ids.filtered(
                lambda m: m.is_check and (not m.journal_id or not m.split_transactions))
            if malos:
                raise UserError(_(
                    'Estos medios de pago están marcados como cheque pero les '
                    'falta configuración: %(medios)s.\n\n'
                    'Necesitan un diario (el de cheques de terceros) y la opción '
                    '«Identificar al cliente» activada. Sin eso, los cobros se '
                    'agrupan en un solo pago y no se puede saber a qué cheque '
                    'corresponde cada uno.',
                    medios=', '.join(malos.mapped('display_name'))))

    def action_pos_session_open(self):
        self._yg_check_config()
        return super().action_pos_session_open()
