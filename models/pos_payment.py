from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PosPayment(models.Model):
    _inherit = 'pos.payment'

    # ── Los cuatro que hacen que el cheque EXISTA ─────────────────────────
    # Sin estos, lo que entra es un cobro genérico: no se puede depositar, no
    # se puede reclamar y no queda en cartera. Por eso son obligatorios.
    check_number = fields.Char(
        string='Número de cheque', index=True,
        help='Número impreso en el cheque. Es lo que lo identifica ante el '
             'banco.')
    check_bank_id = fields.Many2one(
        'res.bank', string='Banco',
        help='Banco contra el que está librado el cheque.')
    check_issuer_vat = fields.Char(
        string='CUIT del librador',
        help='CUIT de quien firma el cheque. Puede no ser el mismo cliente que '
             'compra: un cheque de un tercero endosado es válido.')
    check_payment_date = fields.Date(
        string='Fecha de cobro',
        help='Fecha a partir de la cual el cheque se puede cobrar. En un '
             'cheque de pago diferido es la que define cuándo entra la plata.')

    # El TIPO también es obligatorio, y no por gusto nuestro: `l10n_latam_check`
    # exige que todo cheque esté clasificado (Ley 24.452 / Comunicación BCRA) y
    # RECHAZA EL CIERRE DE CAJA si falta. Si no se pide acá, el cajero se entera
    # al final del día, con el cliente hace rato afuera. Medido el 10/09 haciendo
    # el circuito completo.
    check_type = fields.Selection(
        [('at_sight', 'A la vista'),
         ('cpd', 'Pago diferido (CPD)'),
         ('echeq', 'Echeq')],
        string='Tipo de cheque')

    # ── Complementario: se carga si está, no frena la venta ───────────────
    check_issue_date = fields.Date(string='Fecha de emisión')

    # `is_check` viaja al cobro para que las vistas y la validación no tengan
    # que ir a buscarlo al medio de pago en cada línea.
    is_check = fields.Boolean(
        related='payment_method_id.is_check', store=True, string='Es cheque')

    # Los cuatro obligatorios, en un solo lugar: lo lee la validación de acá y
    # sirve de referencia para la pantalla.
    _CAMPOS_OBLIGATORIOS = (
        ('check_number', 'número de cheque'),
        ('check_bank_id', 'banco'),
        ('check_issuer_vat', 'CUIT del librador'),
        ('check_payment_date', 'fecha de cobro'),
        ('check_type', 'tipo de cheque'),
    )

    @staticmethod
    def _yg_cuit_valido(cuit):
        """Dígito verificador del CUIT (módulo 11).

        La localización lo valida al crear el cheque y **rechaza el cierre de
        caja** si no cierra. Se comprueba acá para que el cajero lo vea al
        cargar el cheque, no al final del día.
        """
        d = ''.join(ch for ch in str(cuit or '') if ch.isdigit())
        if len(d) != 11:
            return False
        pesos = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
        suma = sum(int(a) * b for a, b in zip(d[:10], pesos))
        resto = suma % 11
        ver = 0 if resto == 0 else (9 if resto == 1 else 11 - resto)
        return ver == int(d[10])

    @api.constrains('check_number', 'check_bank_id', 'check_issuer_vat',
                    'check_payment_date', 'check_type', 'amount')
    def _check_check_data(self):
        """Los datos del cheque son obligatorios en los cobros con cheque.

        Se valida en el servidor además de en la pantalla: la validación del
        POS se puede saltear con una sincronización directa, y un cheque sin
        número o sin banco es plata que después nadie puede depositar.

        Los cobros de importe cero (una devolución que compensa) no lo exigen.

        OJO — `is_check` NO VA EN EL @api.constrains, aunque la validación lo
        lea. Es un related ALMACENADO: al marcar «Es cheque» en un medio de
        pago, Odoo lo recalcula en TODOS los cobros ya hechos con ese medio, y
        si el campo dispara la restricción, la validación corre hacia atrás
        sobre historia cerrada — un cambio de CONFIGURACIÓN queda trabado por
        cobros viejos que nadie va a completar nunca. Le pasó a
        `yaguven_pos_tarjeta` el 08/09/2026 con dos cobros de prueba del 25-ago.
        """
        for pago in self:
            if not pago.is_check or not pago.amount:
                continue
            faltan = [etiqueta for campo, etiqueta in self._CAMPOS_OBLIGATORIOS
                      if not pago[campo]]
            if faltan:
                raise ValidationError(_(
                    'Faltan datos del cheque del cobro con %(medio)s: '
                    '%(faltan)s.\n\n'
                    'Sin esos datos el cheque no queda registrado y después no '
                    'se puede depositar ni reclamar.',
                    medio=pago.payment_method_id.display_name,
                    faltan=', '.join(faltan)))
            if not self._yg_cuit_valido(pago.check_issuer_vat):
                raise ValidationError(_(
                    'El CUIT del librador (%(cuit)s) no es válido: no cierra el '
                    'dígito verificador.\n\n'
                    'Conviene corregirlo ahora, con el cheque a la vista: si '
                    'queda mal, el cierre de caja del día no va a poder '
                    'confirmarse.',
                    cuit=pago.check_issuer_vat))

    @api.model
    def _load_pos_data_fields(self, config):
        """Campos que el POS baja al abrir la sesión.

        Sin declararlos acá el navegador no los conoce y se pierden al
        sincronizar, aunque la pantalla los muestre.

        OJO — UNA LISTA VACIA SIGNIFICA «TODOS LOS CAMPOS», NO «NINGUNO».
        Lo decide `pos.session._load_pos_data_relations`:

            if (name not in fields and len(fields)) or ...: continue

        Con `fields == []` la condición nunca corta y baja el modelo entero;
        apenas la lista tiene un elemento, pasa a ser restrictiva. `pos.payment`
        NO define este método en el core (cae en el mixin, que devuelve `[]`),
        así que sumarle nombres al `super()` deja al POS conociendo SOLO los
        nombres sumados: sin `pos_order_id` ni `payment_method_id`, y el POS no
        cobra con NINGUN medio de pago. Lupatini, 08/09/2026: 12 días trabado.

        Por eso, si el super devuelve vacío se devuelve vacío: los campos de
        abajo ya vienen incluidos dentro de «todos».
        """
        fields_list = super()._load_pos_data_fields(config)
        if not fields_list:
            return fields_list
        return fields_list + [
            'check_number', 'check_bank_id', 'check_issuer_vat',
            'check_payment_date', 'check_issue_date', 'check_type',
            'is_check',
        ]
