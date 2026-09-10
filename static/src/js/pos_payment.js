import { PosPayment } from "@point_of_sale/app/models/pos_payment";
import { patch } from "@web/core/utils/patch";

/**
 * Los datos del cheque viven en la línea de pago del POS.
 *
 * Se declaran acá y en `_load_pos_data_fields` del lado servidor: si faltan en
 * cualquiera de los dos lados, el cajero los tipea, la pantalla los muestra, y
 * se pierden al sincronizar sin ningún error visible.
 */
patch(PosPayment.prototype, {
    setup(vals) {
        super.setup(...arguments);
        this.check_number = vals.check_number || "";
        this.check_issuer_vat = vals.check_issuer_vat || "";
        this.check_payment_date = vals.check_payment_date || "";
        this.check_issue_date = vals.check_issue_date || "";
        this.check_is_echeq = vals.check_is_echeq || false;
        // `check_bank_id` NO se inicializa acá: es una relación y la resuelve el
        // modelo relacional del POS. Asignarle "" la rompe.
    },

    /** ¿este cobro es con cheque? */
    get isCheckPayment() {
        return Boolean(this.payment_method_id?.is_check);
    },

    /**
     * Qué datos del cheque faltan. Devuelve la lista de nombres, no un booleano,
     * para poder decirle al cajero QUÉ le falta en vez de sólo que algo falta.
     *
     * Los cobros de importe cero (una devolución que compensa) no exigen nada.
     */
    get missingCheckData() {
        if (!this.isCheckPayment || !this.getAmount()) {
            return [];
        }
        const faltan = [];
        if (!String(this.check_number || "").trim()) {
            faltan.push("número");
        }
        if (!this.check_bank_id) {
            faltan.push("banco");
        }
        if (!String(this.check_issuer_vat || "").trim()) {
            faltan.push("CUIT del librador");
        }
        if (!this.check_payment_date) {
            faltan.push("fecha de cobro");
        }
        return faltan;
    },

    export_for_printing() {
        const res = super.export_for_printing(...arguments);
        // El número en el ticket: es lo que le permite al cliente identificar
        // qué cheque entregó si después hay que discutirlo.
        if (this.isCheckPayment && this.check_number) {
            res.check_number = this.check_number;
            res.check_bank_name = this.check_bank_id?.name || "";
        }
        return res;
    },
});
