/**
 * Bilbao Transit Card — tarjeta Lovelace de la integración Bilbao Transit.
 *
 * Sin dependencias. Pinta una tarjeta por salida, ordenadas por lo que llega
 * antes, con el vehículo colocado en una vía según los minutos que faltan.
 */

const REDES = {
  metro: { color: "#e4002b", emoji: "🚇" },
  tram: { color: "#00a3a1", emoji: "🚊" },
  bizkaibus: { color: "#f0a500", emoji: "🚌" },
  bilbobus: { color: "#2e7dd1", emoji: "🚌" },
};

const TEXTOS = {
  es: { en_directo: "en directo", horario: "horario", sin_servicio: "sin servicio", luego: "luego", vacio: "No hay salidas ahora mismo", min: "min" },
  en: { en_directo: "live", horario: "timetable", sin_servicio: "no service", luego: "then", vacio: "No departures right now", min: "min" },
};

const CSS = `
  :host { display: block; }
  .cab { display: flex; align-items: baseline; justify-content: space-between; padding: 2px 4px 12px; }
  .cab h2 { margin: 0; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
            font-size: 19px; font-weight: 600; letter-spacing: .2px; color: var(--primary-text-color); }
  .cab h2 span { color: var(--secondary-text-color); font-weight: 400; font-size: 13px; }
  .cab .ahora { flex: 0 0 auto; padding-left: 10px; font-size: 12.5px; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
  .lista { display: flex; flex-direction: column; gap: 10px; }
  .t { position: relative; display: grid; grid-template-columns: 52px 88px minmax(0, 1fr); gap: 12px; align-items: center;
       padding: 13px 15px 28px; border-radius: 18px; overflow: hidden;
       background: var(--bt-fondo, linear-gradient(160deg,#171d28 0%,#131822 100%));
       border: 1px solid var(--bt-borde, #222a38); }
  .t::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--c); }
  .badge { width: 52px; height: 52px; border-radius: 15px; display: grid; place-items: center; font-size: 24px;
           background: var(--cbg); border: 1px solid var(--clinea); }
  .mins { text-align: center; line-height: 1; }
  .mins b { display: block; font-size: 38px; font-weight: 700; letter-spacing: -1.5px; color: var(--bt-num, var(--primary-text-color));
            font-variant-numeric: tabular-nums; transition: color .3s ease; }
  .mins i { font-style: normal; font-size: 11.5px; letter-spacing: 1.8px; text-transform: uppercase; color: var(--bt-min, var(--secondary-text-color)); }
  .info { min-width: 0; }
  .dest { font-size: 16px; font-weight: 600; color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .meta { margin-top: 3px; font-size: 12.5px; color: var(--secondary-text-color); display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
  .prox { grid-column: 1 / -1; display: flex; align-items: stretch; gap: 7px; margin-top: 4px; }
  .prox .p { flex: 1 1 0; max-width: 104px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1px;
             padding: 6px 4px; border-radius: 12px; background: var(--cbg); border: 1px solid var(--clinea); }
  .prox .p b { font-size: 25px; font-weight: 700; line-height: 1; letter-spacing: -1px;
               color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
  .prox .p i { font-style: normal; font-size: 9.5px; line-height: 1; letter-spacing: 1.2px;
               text-transform: uppercase; color: var(--secondary-text-color); }
  .lin { padding: 1px 7px; border-radius: 6px; background: var(--cbg); border: 1px solid var(--clinea); color: var(--primary-text-color); font-weight: 600; font-size: 11.5px; }
  .live { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: #3ddc84; animation: bt-brillo 2.2s ease-in-out infinite; }
  .dot.gris { background: #7b8494; animation: none; }
  .via { position: absolute; left: 15px; right: 15px; bottom: 12px; height: 12px; }
  .rail { position: absolute; inset: 5px 0 auto; height: 3px; border-radius: 2px;
          background: repeating-linear-gradient(90deg, var(--bt-rail, #3d4859) 0 12px, transparent 12px 24px);
          animation: bt-carril 1.6s linear infinite; }
  .veh { position: absolute; top: 0; width: 17px; height: 12px; border-radius: 3px; background: var(--c);
         display: flex; align-items: center; justify-content: center; gap: 2px;
         box-shadow: 0 0 12px -2px var(--c); animation: bt-vaiven 1.8s ease-in-out infinite;
         transition: left 1.2s cubic-bezier(.4,0,.2,1); }
  .veh em { display: block; width: 3px; height: 4px; border-radius: 1px; background: rgba(0,0,0,.45); }
  .veh::after { content: ''; position: absolute; inset: 0; border-radius: 3px;
                background: linear-gradient(90deg, transparent, rgba(255,255,255,.35), transparent);
                animation: bt-brillo 2.6s ease-in-out infinite; }
  .fin { position: absolute; right: 0; top: 2px; width: 6px; height: 8px; border-radius: 2px;
         background: var(--bt-rail, #3a4456); animation: bt-vias 3s ease-in-out infinite; }
  .t.ya { border-color: rgba(228,0,43,.32); animation: bt-pulso 2.6s ease-in-out infinite; }
  .t.ya::before { width: 5px; box-shadow: 0 0 14px 1px rgba(228,0,43,.8); }
  .t.ya .mins b { color: #ff5b6e; }
  .vacio { padding: 18px; text-align: center; color: var(--secondary-text-color); font-size: 13.5px; }
  @keyframes bt-brillo { 0%,100% { opacity: .45 } 50% { opacity: 1 } }
  @keyframes bt-pulso { 0%,100% { box-shadow: 0 0 0 0 rgba(228,0,43,.45) } 50% { box-shadow: 0 0 0 9px rgba(228,0,43,0) } }
  @keyframes bt-vaiven { 0%,100% { transform: translateX(0) } 50% { transform: translateX(3px) } }
  @keyframes bt-carril { from { background-position: 0 0 } to { background-position: 24px 0 } }
  @keyframes bt-vias { 0%,100% { opacity: .35 } 50% { opacity: .75 } }
  @media (prefers-reduced-motion: reduce) {
    .rail, .veh, .veh::after, .dot, .fin, .t.ya { animation: none !important; }
  }
`;

class BilbaoTransitCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._filas = new Map();
    this._montado = false;
  }

  static getStubConfig() {
    return { title: "Transporte", max: 8 };
  }

  setConfig(config) {
    this._config = { title: "Transporte", max: 8, siguientes: 2, ...config };
    this._montado = false;
    try {
      this._render();
    } catch (err) {
      this._mostrarError(err);
    }
  }

  set hass(hass) {
    this._hass = hass;
    try {
      this._render();
    } catch (err) {
      this._mostrarError(err);
    }
  }

  getCardSize() {
    return 3 + (this._filas.size || 4) * 1.5;
  }

  getGridOptions() {
    return { columns: "full", rows: "auto", min_columns: 6 };
  }

  // si algo falla, se ve el motivo en la tarjeta en vez de romper el dashboard
  _mostrarError(err) {
    if (!this.shadowRoot) return;
    const mensaje = err && err.message ? err.message : String(err);
    this.shadowRoot.innerHTML =
      '<div style="padding:16px;font:14px system-ui;color:var(--error-color)">' +
      "Error en la tarjeta de Bilbao Transit: " +
      mensaje +
      "</div>";
  }

  _t(clave) {
    const idioma = (this._hass?.language || "es").slice(0, 2);
    return (TEXTOS[idioma] || TEXTOS.es)[clave];
  }

  _salidas() {
    const estados = this._hass?.states || {};
    const ids = this._config.entities;
    const lista = [];
    for (const [id, entidad] of Object.entries(estados)) {
      if (!id.startsWith("sensor.")) continue;
      if (ids && !ids.includes(id)) continue;
      const a = entidad.attributes || {};
      if (!a.network_key || !Array.isArray(a.next_departures)) continue;
      const salidas = a.next_departures;
      if (!salidas.length) continue;
      const minutos = a.next_minutes ?? salidas[0].minutes ?? 0;
      lista.push({ id, attrs: a, salidas, minutos: Number(minutos) });
    }
    return lista.sort((x, y) => x.minutos - y.minutos).slice(0, this._config.max);
  }

  _render() {
    if (!this._hass) return;
    if (!this._montado) {
      this.shadowRoot.innerHTML = `<style>${CSS}</style>
        <div class="cab"><h2></h2><div class="ahora"></div></div>
        <div class="lista"></div>`;
      this._montado = true;
      this._filas.clear();
    }
    const datos = this._salidas();
    const titulo = this.shadowRoot.querySelector(".cab h2");
    titulo.innerHTML = `${this._config.title} <span>· lo que llega antes</span>`;
    this.shadowRoot.querySelector(".ahora").textContent =
      new Date().toLocaleTimeString(this._hass.language || "es", { hour: "2-digit", minute: "2-digit" });

    const contenedor = this.shadowRoot.querySelector(".lista");
    if (!datos.length) {
      contenedor.innerHTML = `<div class="vacio">${this._t("vacio")}</div>`;
      this._filas.clear();
      return;
    }
    if (contenedor.querySelector(".vacio")) contenedor.innerHTML = "";

    const vistos = new Set();
    datos.forEach((dato, indice) => {
      vistos.add(dato.id);
      let fila = this._filas.get(dato.id);
      if (!fila) {
        fila = this._crearFila(dato.id);
        this._filas.set(dato.id, fila);
      }
      this._actualizarFila(fila, dato);
      if (contenedor.children[indice] !== fila) {
        contenedor.insertBefore(fila, contenedor.children[indice] || null);
      }
    });
    for (const [id, fila] of this._filas) {
      if (!vistos.has(id)) {
        fila.remove();
        this._filas.delete(id);
      }
    }
  }

  _crearFila(id) {
    const fila = document.createElement("div");
    fila.className = "t";
    fila.innerHTML = `
      <div class="badge"></div>
      <div class="mins"><b></b><i>${this._t("min")}</i></div>
      <div class="info">
        <div class="dest"></div>
        <div class="meta"><span class="lin"></span><span class="hora"></span><span class="live"><span class="dot"></span><span class="txt"></span></span></div>
      </div>
      <div class="prox"></div>
      <div class="via"><div class="rail"></div><div class="veh"><em></em><em></em></div><div class="fin"></div></div>`;
    fila.dataset.entity = id;
    fila.addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: id }, bubbles: true, composed: true }));
    });
    fila.style.cursor = "pointer";
    return fila;
  }

  _actualizarFila(fila, dato) {
    const { attrs, salidas, minutos } = dato;
    const red = REDES[attrs.network_key] || { color: "#7b8494", emoji: attrs.network_emoji || "🚏" };
    const urgente = minutos <= 3;

    fila.style.setProperty("--c", red.color);
    fila.style.setProperty("--cbg", red.color + "1f");
    fila.style.setProperty("--clinea", red.color + "59");
    fila.classList.toggle("ya", urgente);

    fila.querySelector(".badge").textContent = attrs.network_emoji || red.emoji;
    fila.querySelector(".mins b").textContent = minutos;
    const linea = fila.querySelector(".lin");
    const lineaTexto = salidas[0].line || "";
    linea.textContent = lineaTexto;
    linea.style.display = lineaTexto ? "" : "none";

    let destino = attrs.direction_label || attrs.destination || attrs.network;
    if (lineaTexto && destino.startsWith(lineaTexto)) {
      destino = destino.slice(lineaTexto.length).replace(/^[·\-\s]+/, "").trim() || lineaTexto;
    }
    fila.querySelector(".dest").textContent = destino;

    const hora = fila.querySelector(".hora");
    hora.textContent = salidas[0].departure || "";

    // las siguientes salidas, en grande: sirven para decidir si da tiempo a bajar
    const prox = fila.querySelector(".prox");
    const cuantas = Math.max(0, Number(this._config.siguientes ?? 2));
    const siguientes = salidas.slice(1, 1 + cuantas);
    const claveProx = siguientes.map((s) => s.minutes).join("|");
    if (prox.dataset.clave !== claveProx) {
      prox.dataset.clave = claveProx;
      prox.innerHTML = siguientes
        .map(
          (s) =>
            '<div class="p"><b>' +
            s.minutes +
            "</b><i>" +
            this._t("min") +
            "</i></div>"
        )
        .join("");
      prox.style.display = siguientes.length ? "" : "none";
    }

    const enDirecto = attrs.data_source === "realtime";
    fila.querySelector(".dot").classList.toggle("gris", !enDirecto);
    fila.querySelector(".live .txt").textContent = enDirecto ? this._t("en_directo") : this._t("horario");

    // la posición en la vía indica cuánto falta: 0 min al final, 30+ al principio
    const posicion = Math.max(4, 92 - minutos * 2.8);
    fila.querySelector(".veh").style.left = `${posicion}%`;
  }
}

if (!customElements.get("bilbao-transit-card")) {
  customElements.define("bilbao-transit-card", BilbaoTransitCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "bilbao-transit-card")) {
  window.customCards.push({
    type: "bilbao-transit-card",
    name: "Bilbao Transit",
    description: "Próximas salidas de metro, tranvía y bus, ordenadas por lo que llega antes.",
    preview: true,
  });
}
