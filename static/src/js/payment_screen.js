import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

/**
 * No deja validar la venta si faltan datos del cheque.
 *
 * El servidor también lo valida (`_check_check_data`): esto es para que el
 * cajero se entere ACÁ, con el cheque todavía en la mano, y no después con un
 * error de sincronización que no sabe cómo resolver.
 */
patch(PaymentScreen.prototype, {
    /**
     * Los bancos para el desplegable. Vienen de `res.bank`, que este módulo
     * suma a los modelos que el POS baja al abrir la sesión.
     *
     * `this.pos.models["<modelo>"].getAll()` es el acceso real en O19,
     * verificado en el core (`pos_config.js`, `partner_list.js`).
     */
    get chequeBancos() {
        return this.pos.models["res.bank"]?.getAll() || [];
    },

    /** Graba un dato del cheque en la línea de pago. */
    setCheckField(line, campo, valor) {
        // El record del POS es reactivo: asignarle el campo ya propaga a la
        // orden y a la pantalla.
        line[campo] = typeof valor === "string" ? valor.trim() : valor;
    },

    /** El banco es una relación: se guarda el RECORD, no el id. */
    setCheckBank(line, bankId) {
        const id = parseInt(bankId, 10);
        line.check_bank_id = id ? this.pos.models["res.bank"].get(id) : false;
    },

    async validateOrder(isForceValidate) {
        // `this.paymentLines` es el getter de la propia pantalla. En O19 la
        // orden NO tiene `getPaymentlines()`: llamarlo corta el botón Validar.
        const incompletas = this.paymentLines.filter(
            (linea) => linea.missingCheckData?.length
        );

        if (incompletas.length) {
            const detalle = incompletas
                .map((l) => `${l.payment_method_id.name}: ${l.missingCheckData.join(", ")}`)
                .join("\n");
            this.dialog.add(AlertDialog, {
                title: _t("Faltan datos del cheque"),
                body: _t(
                    "Cargá los datos que faltan:\n\n%s\n\n" +
                        "Sin ellos el cheque no queda registrado y después no se " +
                        "puede depositar ni reclamar.",
                    detalle
                ),
            });
            return;
        }
        return super.validateOrder(isForceValidate);
    },
});
