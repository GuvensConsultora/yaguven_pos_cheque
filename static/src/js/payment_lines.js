import { PaymentScreenPaymentLines } from "@point_of_sale/app/screens/payment_screen/payment_lines/payment_lines";
import { patch } from "@web/core/utils/patch";
import { onMounted, onPatched } from "@odoo/owl";

/** Los cuatro obligatorios, y los dos opcionales. */
const CAMPOS = [
    { k: "check_number", et: "Número *", tipo: "text", req: true, ph: "del cheque" },
    { k: "check_bank_id", et: "Banco *", tipo: "select", req: true },
    { k: "check_issuer_vat", et: "CUIT librador *", tipo: "text", req: true, ph: "quien firma" },
    { k: "check_payment_date", et: "Fecha de cobro *", tipo: "date", req: true },
    { k: "check_issue_date", et: "Emisión", tipo: "date" },
    { k: "check_is_echeq", et: "e-cheq", tipo: "check" },
];

/**
 * Dibuja los datos del cheque en el DOM, en vez de declararlos en el template.
 *
 * POR QUE ASI Y NO CON UN TEMPLATE: cualquier `t-if` o `t-foreach` dentro de un
 * xpath heredado sobre `PaymentScreenPaymentLines` hace que OWL descarte el
 * template ENTERO, en silencio y sin error — el POS carga igual y el cajero
 * simplemente no ve donde escribir. Se probaron cinco variantes el 10/09 y la
 * unica que se inserta es un `div` fijo. De ahi que el template aporte solo el
 * contenedor `.yg-check-host` y el contenido se arme aca.
 */
patch(PaymentScreenPaymentLines.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => this._ygPintarCheque());
        onPatched(() => this._ygPintarCheque());
    },

    /** La linea de cheque que el cajero esta editando, o ninguna. */
    get ygLineaCheque() {
        const ls = this.props.paymentLines || [];
        return ls.find((l) => l.isSelected?.() && l.isCheckPayment) ||
               ls.find((l) => l.isCheckPayment);
    },

    _ygPintarCheque() {
        const host = document.querySelector(".yg-check-host");
        if (!host) {
            return;
        }
        const line = this.ygLineaCheque;
        if (!line) {
            host.innerHTML = "";
            host.dataset.ygUuid = "";
            return;
        }
        // Redibujar en cada tecla haria perder el foco del input: solo se arma
        // cuando cambia la linea.
        if (host.dataset.ygUuid === line.uuid) {
            this._ygMarcarFaltantes(host, line);
            return;
        }
        host.dataset.ygUuid = line.uuid;
        host.innerHTML = "";

        const caja = document.createElement("div");
        caja.className = "yg-check-data d-flex flex-wrap gap-2 p-2 mt-2 border rounded-3";
        caja.style.flexBasis = "100%";
        const tit = document.createElement("div");
        tit.className = "w-100 fw-bold small text-muted";
        tit.textContent = `Datos del cheque — ${line.payment_method_id.name}`;
        caja.appendChild(tit);

        for (const c of CAMPOS) {
            const col = document.createElement("div");
            col.className = "d-flex flex-column";
            const lab = document.createElement("label");
            lab.className = "o_form_label small text-muted";
            lab.textContent = c.et;
            col.appendChild(lab);

            let inp;
            if (c.tipo === "select") {
                inp = document.createElement("select");
                inp.className = "form-select form-select-sm";
                inp.appendChild(new Option("— elegir —", ""));
                for (const b of this.pos.models["res.bank"]?.getAll() || []) {
                    const o = new Option(b.name, b.id);
                    o.selected = line.check_bank_id?.id === b.id;
                    inp.appendChild(o);
                }
                inp.onchange = (ev) => {
                    const id = parseInt(ev.target.value, 10);
                    line.check_bank_id = id ? this.pos.models["res.bank"].get(id) : false;
                    this._ygMarcarFaltantes(host, line);
                };
            } else if (c.tipo === "check") {
                inp = document.createElement("input");
                inp.type = "checkbox";
                inp.className = "form-check-input";
                inp.checked = !!line[c.k];
                inp.onchange = (ev) => (line[c.k] = ev.target.checked);
            } else {
                inp = document.createElement("input");
                inp.type = c.tipo;
                inp.className = "form-control form-control-sm";
                if (c.ph) {
                    inp.placeholder = c.ph;
                }
                inp.value = line[c.k] || "";
                inp.onchange = (ev) => {
                    line[c.k] = ev.target.value.trim();
                    this._ygMarcarFaltantes(host, line);
                };
            }
            inp.dataset.ygCampo = c.k;
            col.appendChild(inp);
            caja.appendChild(col);
        }
        host.appendChild(caja);
        this._ygMarcarFaltantes(host, line);
    },

    /** Borde naranja en lo que falta. Naranja y no rojo: el usuario es daltonico,
        y ademas el asterisco de la etiqueta ya marca cual es obligatorio. */
    _ygMarcarFaltantes(host, line) {
        for (const c of CAMPOS.filter((x) => x.req)) {
            const el = host.querySelector(`[data-yg-campo="${c.k}"]`);
            if (el) {
                el.classList.toggle("border-warning", !line[c.k]);
            }
        }
    },
});
