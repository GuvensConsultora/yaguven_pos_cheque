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

    def _compute_is_cash_count(self):
        """Los cheques NO se cuentan en el arqueo de efectivo.

        El core lo resuelve con `is_cash_count = type == 'cash'`, y el medio de
        cheque necesita un diario de tipo efectivo —es el único donde la
        localización admite el método de cheques de terceros—. Sin este override
        el cajero tendría que contar los cheques como si fueran billetes al
        cerrar la caja.

        Quedan igual en el desglose por medio de pago del cierre, que es donde
        corresponde verlos: como recuento de cheques, no de efectivo.
        """
        super()._compute_is_cash_count()
        for pm in self.filtered('is_check'):
            pm.is_cash_count = False

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
