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
        'account.journal',
        string='Diario de cheques de terceros',
        domain="[('type', '=', 'cash')]",
        help='Diario donde queda el cheque una vez cobrado. Tiene que ser el de '
             'cheques de terceros de la localización, el mismo que usa '
             'administración: es el que permite después depositarlo, endosarlo '
             'o marcarlo rechazado.\n\n'
             'El medio de pago en cambio va SIN diario. Suena raro y es a '
             'propósito: con diario de efectivo el POS mete los cheques en el '
             'arqueo de caja (el cajero tendría que contarlos como billetes) y '
             'con diario de banco el cheque queda afuera del circuito de la '
             'localización. Sin diario, el cobro queda en la cuenta del cliente '
             'y el pago que crea este módulo la cancela.')

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
