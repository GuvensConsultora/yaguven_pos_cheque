from odoo import api, fields, models


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    is_check = fields.Boolean(
        string='Es cheque',
        help='Marcar en los medios de pago que se cobran con cheque.\n\n'
             'Al cobrar con este medio, el POS pide los datos del cheque '
             '(número, banco, CUIT del librador y fecha de cobro) y no deja '
             'validar la venta sin ellos. Son los datos que después permiten '
             'tener el cheque en cartera y depositarlo.\n\n'
             'Se define acá y no se deduce del nombre del medio de pago: un '
             'medio nuevo funciona sin tocar código.',
    )

    check_journal_id = fields.Many2one(
        'account.journal', string='Diario de cheques de terceros',
        domain="[('type', '=', 'cash'), ('company_id', '=', company_id)]",
        help='Diario donde quedan los cheques en cartera al cerrar la caja. Es el '
             'de efectivo con el método «Cheques de terceros nuevos» de la '
             'localización.\n\nOdoo 20: el medio de cheque va como «Cuenta de '
             'cliente» (sin diario propio), porque cada caja admite un solo medio de '
             'efectivo; el diario de cheques se indica acá.')

    def _yg_faltantes_cheque(self):
        """Qué le falta a un medio de cheque para funcionar (lista vacía = bien)."""
        self.ensure_one()
        falta = []
        if self.type != 'pay_later':
            falta.append('tiene que ser de tipo «Cuenta de cliente», sin diario')
        j = self.check_journal_id
        if not j:
            falta.append('le falta el diario de cheques de terceros')
        elif j.type != 'cash':
            falta.append('el diario de cheques tiene que ser de tipo efectivo')
        elif not j.inbound_payment_method_line_ids.filtered(
                lambda l: l.code == 'new_third_party_checks'):
            falta.append('el diario de cheques no tiene habilitado «Cheques de terceros nuevos»')
        return falta

    @api.model
    def _load_pos_data_fields(self, config):
        """`is_check` tiene que viajar al navegador.

        El core SI define este método para `pos.payment.method`, así que la
        lista ya viene restrictiva y hay que SUMAR. Sin esto el campo llega
        `undefined`, la pantalla del cheque no aparece nunca y no hay ningún
        error a la vista.

        Es el caso inverso al de `pos.payment` — ver el comentario largo en
        pos_payment.py.
        """
        return super()._load_pos_data_fields(config) + ['is_check']
