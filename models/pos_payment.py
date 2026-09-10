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

    # Los mismos plazos que valida `yaguven_payment_group` sobre el cheque ya
    # creado (Ley 24.452 / Comunicación BCRA). Se repiten acá A PROPOSITO: si
    # sólo se validan allá, el cajero se entera al cerrar la caja.
    _LEGAL_DAYS_COMMON = 30
    _LEGAL_DAYS_ECHEQ = 360

    def _yg_check_plazos(self):
        """Fechas coherentes con el tipo de cheque.

        El cheque A LA VISTA también se controla, y no es un detalle: es el
        cheque común, que por la Ley 24.452 tiene 30 días desde la emisión para
        presentarse al cobro. Si alguien lo carga a la vista con fecha de cobro
        a 45 días, lo que tiene en la mano es un cheque de pago diferido mal
        clasificado — y así cargado el plazo real del cheque queda mintiendo en
        el listado de cartera.

        Sin fecha de emisión se toma la de hoy como referencia: un cheque a la
        vista con cobro dentro de un mes largo es sospechoso igual.
        """
        for pago in self:
            if not pago.check_payment_date:
                continue
            emision = pago.check_issue_date
            if pago.check_type == 'at_sight' and not emision:
                emision = fields.Date.context_today(pago)
            if not emision:
                continue
            if pago.check_payment_date < emision:
                raise ValidationError(_(
                    'La fecha de cobro (%(pay)s) no puede ser anterior a la de '
                    'emisión (%(iss)s).',
                    pay=pago.check_payment_date, iss=emision))
            limite = (self._LEGAL_DAYS_ECHEQ if pago.check_type in ('cpd', 'echeq')
                      else self._LEGAL_DAYS_COMMON)
            dias = (pago.check_payment_date - emision).days
            if dias > limite:
                raise ValidationError(_(
                    'Hay %(dias)s días hasta la fecha de cobro, y un %(tipo)s '
                    'admite hasta %(limite)s (Ley 24.452).\n\n'
                    'Si el cheque tiene fecha futura es un cheque de pago '
                    'diferido: marcalo como «Pago diferido (CPD)», o como '
                    '«Echeq» si es electrónico. Esos admiten hasta 360 días.',
                    dias=dias, limite=limite,
                    tipo={'at_sight': 'cheque a la vista',
                          'cpd': 'cheque de pago diferido',
                          'echeq': 'Echeq'}.get(pago.check_type, 'cheque común')))

    def _yg_check_duplicado(self):
        """El número de cheque es único por banco.

        Se busca en los cheques ya en cartera Y en los cobros de sesiones
        abiertas: dos cajas distintas pueden estar cargando el mismo cheque al
        mismo tiempo, y si sólo se mira la cartera el choque aparece recién al
        cerrar.
        """
        for pago in self:
            if not pago.check_number or not pago.check_bank_id:
                continue
            Cheque = self.env.get('l10n_latam.check')
            if Cheque is not None and Cheque.sudo().search_count([
                    ('name', '=', pago.check_number),
                    ('bank_id', '=', pago.check_bank_id.id)]):
                raise ValidationError(_(
                    'El cheque %(nro)s del banco %(banco)s ya está registrado.\n\n'
                    'Cada cheque tiene número único por banco: si es el mismo, '
                    'ya está cobrado; si es otro, revisá el número con el cheque '
                    'a la vista.',
                    nro=pago.check_number, banco=pago.check_bank_id.name))
            otro = self.sudo().search([
                ('id', '!=', pago.id),
                ('check_number', '=', pago.check_number),
                ('check_bank_id', '=', pago.check_bank_id.id),
                ('pos_order_id.session_id.state', '!=', 'closed'),
            ], limit=1)
            if otro:
                raise ValidationError(_(
                    'El cheque %(nro)s del banco %(banco)s ya se cargó en esta '
                    'jornada, en %(donde)s.\n\n'
                    'Si es el mismo cheque, no hace falta cargarlo de nuevo.',
                    nro=pago.check_number, banco=pago.check_bank_id.name,
                    donde=otro.pos_order_id.session_id.display_name))

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
                    'check_payment_date', 'check_issue_date', 'check_type',
                    'amount')
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
            pago._yg_check_plazos()
            pago._yg_check_duplicado()

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
