import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";

patch(PaymentScreen.prototype, {
    setCheckField(line, campo, valor) {
        // El record del POS es reactivo: asignarle el campo ya propaga a la
        // orden y a la pantalla.
        line[campo] = typeof valor === "string" ? valor.trim() : valor;
    },
});

/**
 * No deja validar la venta si faltan datos del cheque.
 *
 * El servidor también lo valida (`_check_check_data`): esto es para que el
 * cajero se entere ACÁ, con el cheque todavía en la mano, y no después con un
 * error de sincronización que no sabe cómo resolver.
 *
 * Odoo 20: el botón Validar pasa por OrderPaymentValidation (también la
 * validación rápida), no por PaymentScreen.validateOrder.
 */
patch(OrderPaymentValidation.prototype, {
    async isOrderValid(isForceValidate) {
        // `this.paymentLines`: las líneas de pago de la orden que se valida.
        const incompletas = this.paymentLines.filter(
            (linea) => linea.missingCheckData?.length
        );

        if (incompletas.length) {
            const detalle = incompletas
                .map((l) => `${l.payment_method_id.name}: ${l.missingCheckData.join(", ")}`)
                .join("\n");
            this.pos.dialog.add(AlertDialog, {
                title: _t("Faltan datos del cheque"),
                body: _t(
                    "Cargá los datos que faltan:\n\n%s\n\n" +
                        "Sin ellos el cheque no queda registrado y después no se " +
                        "puede depositar ni reclamar.",
                    detalle
                ),
            });
            return false;
        }

        // Número fuera de lo habitual (más de 8 dígitos, o algo que no es un
        // número): se AVISA y el cajero decide. No bloquea porque hay cheques
        // válidos con otros formatos (echeq). Misma regla que
        // `yaguven_cheque_nro_control` en Contabilidad.
        const raros = this.paymentLines.filter((linea) => {
            if (!linea.isCheckPayment) {
                return false;
            }
            const nro = String(linea.check_number || "").trim();
            return nro && (!/^\d+$/.test(nro) || nro.length > 8);
        });
        if (raros.length) {
            const detalle = raros.map((l) => String(l.check_number).trim()).join(", ");
            const seguir = await ask(this.pos.dialog, {
                title: _t("Revisá el número del cheque"),
                body: _t(
                    "El número %s tiene más de 8 dígitos o algo que no es un número.\n\n" +
                        "Compará contra el cheque. Si está bien, podés seguir.",
                    detalle
                ),
                confirmLabel: _t("Está bien, seguir"),
                cancelLabel: _t("Corregir"),
            });
            if (!seguir) {
                return false;
            }
        }
        return super.isOrderValid(isForceValidate);
    },
});
