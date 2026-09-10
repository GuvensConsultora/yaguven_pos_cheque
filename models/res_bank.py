from odoo import api, models


class ResBank(models.Model):
    # Patrón del core para enganchar un modelo que NO es del POS a la carga de
    # datos de la sesión: `_name` + `_inherit` con el mixin. Copiado de
    # `point_of_sale/models/res_country.py`, verificado en el core de esta
    # instancia — sin el mixin, agregar el modelo a `_load_pos_data_models`
    # revienta al abrir la sesión.
    _name = 'res.bank'
    _inherit = ['res.bank', 'pos.load.mixin']

    @api.model
    def _load_pos_data_fields(self, config):
        """Los bancos que el POS baja para el desplegable del cheque.

        Se baja la lista al navegador (36 bancos en Lupatini) para que el cajero
        ELIJA el banco en vez de tipearlo. Un nombre tipeado a mano no aparea
        contra `res.bank` después, y el cheque queda sin banco — que es uno de
        los datos sin los cuales no se puede depositar.
        """
        return ['id', 'name', 'bic']

    @api.model
    def _load_pos_data_domain(self, data, config):
        """Todos los bancos activos: son pocos y no cambian seguido."""
        return []
