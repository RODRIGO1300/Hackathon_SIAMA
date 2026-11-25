/*
 * <siama-huecos> — Componente web embebible para los tableros de SIAMA
 * (Monitor Precipitaciones / Monitor Temperaturas).
 *
 * Uso (HTML, React, Django templates... cualquier página):
 *   <script src="https://<servidor>/web/siama-huecos.js"></script>
 *   <siama-huecos api="https://<servidor>" variable="precipitacion" vista="completo"></siama-huecos>
 *
 * Atributos:
 *   api       URL base de la API (por defecto, el mismo origen)
 *   variable  precipitacion | tmax | tmin
 *   estacion  clave de estación inicial (opcional)
 *   vista     completo | mapa | serie
 *   desde, hasta  AAAA-MM-DD (opcional; por defecto el último año con datos)
 *   selector  "no" para ocultar la barra de controles (cuando el tablero ya tiene los suyos)
 *
 * Evento: "siama-estacion" (detail: {clave}) al elegir una estación en el mapa.
 * Tema: se adapta con variables CSS --shg-observado, --shg-estimado, --shg-fuente, etc.
 */
(function () {
  const CDN = {
    leafletCss: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css",
    leaflet: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js",
    plotly: "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js",
  };
  const NOMBRES = { precipitacion: "Precipitación diaria", tmax: "Temperatura máxima", tmin: "Temperatura mínima" };
  const UNIDAD = { precipitacion: "mm", tmax: "°C", tmin: "°C" };
  const METODO = {
    interp_lineal: "interpolación con días vecinos", idw: "estaciones cercanas (IDW)",
    normal: "estaciones vecinas correlacionadas", ml: "modelo de aprendizaje automático",
    ensamble: "combinación de métodos",
  };
  const promesas = {};
  function script(src) {
    if (!promesas[src]) promesas[src] = new Promise((ok, mal) => {
      const s = document.createElement("script"); s.src = src; s.onload = ok;
      s.onerror = () => mal(new Error(`no se pudo cargar ${src}`)); document.head.appendChild(s);
    });
    return promesas[src];
  }
  function css(href) {
    if (document.querySelector(`link[href="${href}"]`)) return;
    const l = document.createElement("link"); l.rel = "stylesheet"; l.href = href; document.head.appendChild(l);
  }
  function estilos() {
    if (document.getElementById("shg-estilos")) return;
    const st = document.createElement("style"); st.id = "shg-estilos";
    st.textContent = `
siama-huecos{display:block;--shg-observado:#1f4e79;--shg-estimado:#c2570c;--shg-banda:rgba(194,87,12,.18);
 --shg-noest:rgba(120,120,120,.18);--shg-fuente:inherit;--shg-borde:#d9dee5;--shg-fondo:#fff;--shg-texto:#1d2733;--shg-suave:#5b6776}
.shg{font-family:var(--shg-fuente);color:var(--shg-texto);background:var(--shg-fondo);border:1px solid var(--shg-borde);border-radius:10px;overflow:hidden}
.shg-barra{display:flex;flex-wrap:wrap;gap:12px;align-items:end;padding:10px 14px;border-bottom:1px solid var(--shg-borde)}
.shg-barra label{display:flex;flex-direction:column;font-size:12px;color:var(--shg-suave);gap:3px}
.shg-barra select,.shg-barra input{font:inherit;font-size:14px;padding:4px 6px;border:1px solid var(--shg-borde);border-radius:6px;background:#fff;color:var(--shg-texto)}
.shg-cuerpo{display:grid;grid-template-columns:minmax(260px,1fr) 2fr}
.shg[data-vista=mapa] .shg-cuerpo,.shg[data-vista=serie] .shg-cuerpo{grid-template-columns:1fr}
@media (max-width:760px){.shg-cuerpo{grid-template-columns:1fr}}
.shg-mapa{min-height:380px;position:relative;border-right:1px solid var(--shg-borde)}
.shg-panel{padding:12px 14px;min-width:0}
.shg-titulo{font-weight:600;font-size:15px}
.shg-sub{font-size:12px;color:var(--shg-suave);margin-top:2px}
.shg-chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 4px}
.shg-chip{font-size:12px;padding:3px 8px;border-radius:999px;border:1px solid var(--shg-borde);white-space:nowrap}
.shg-chip i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.shg-grafica{height:340px}
.shg-ayuda{font-size:12px;color:var(--shg-suave);line-height:1.45;margin-top:6px}
.shg-ayuda b{color:var(--shg-texto)}
.shg-leyenda-mapa{position:absolute;z-index:500;bottom:10px;left:10px;background:#fff;border:1px solid var(--shg-borde);border-radius:6px;padding:6px 8px;font-size:11px;line-height:1.6}
.shg-leyenda-mapa i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}
.shg-error{padding:12px;color:#a61b1b;font-size:13px}`;
    document.head.appendChild(st);
  }
  const colorVacios = (p) => p < 5 ? "#2e7d32" : p < 15 ? "#f9a825" : p < 30 ? "#ef6c00" : "#c62828";
  const fmt = (v, u) => v == null ? "—" : `${Number(v).toFixed(1)} ${u}`;

  class SiamaHuecos extends HTMLElement {
    static get observedAttributes() { return ["estacion", "variable", "desde", "hasta"]; }
    get api() { return (this.getAttribute("api") || "").replace(/\/$/, ""); }
    get variable() { return this.getAttribute("variable") || "precipitacion"; }
    get vista() { return this.getAttribute("vista") || "completo"; }

    async connectedCallback() {
      if (this._iniciado) return; this._iniciado = true;
      estilos(); css(CDN.leafletCss);
      const conMapa = this.vista !== "serie";
      this.innerHTML = `
<div class="shg" data-vista="${this.vista}">
  <div class="shg-barra" ${this.getAttribute("selector") === "no" ? "hidden" : ""}>
    <label>Variable<select data-r="variable">
      <option value="precipitacion">Precipitación</option><option value="tmax">Temperatura máxima</option><option value="tmin">Temperatura mínima</option>
    </select></label>
    <label>Estación<select data-r="estacion"></select></label>
    <label>Desde<input type="date" data-r="desde"></label>
    <label>Hasta<input type="date" data-r="hasta"></label>
  </div>
  <div class="shg-cuerpo">
    ${conMapa ? `<div class="shg-mapa" data-r="mapa"><div class="shg-leyenda-mapa"><b>% de días sin dato</b><br>
      <i style="background:#2e7d32"></i>menos de 5%<br><i style="background:#f9a825"></i>5–15%<br>
      <i style="background:#ef6c00"></i>15–30%<br><i style="background:#c62828"></i>más de 30%</div></div>` : ""}
    ${this.vista !== "mapa" ? `<div class="shg-panel">
      <div class="shg-titulo" data-r="titulo">Cargando…</div><div class="shg-sub" data-r="sub"></div>
      <div class="shg-chips" data-r="chips"></div>
      <div class="shg-grafica" data-r="grafica"></div>
      <div class="shg-ayuda"><b>Cómo leer esta gráfica:</b> la línea <b style="color:var(--shg-observado)">sólida azul</b> son datos medidos por la estación.
        La línea <b style="color:var(--shg-estimado)">punteada naranja</b> son datos <b>estimados</b> para llenar días sin medición; la franja sombreada indica
        el rango donde, con 90% de probabilidad, está el valor real. Las zonas grises son periodos que <b>no se estimaron</b> porque no había información confiable.</div>
    </div>` : ""}
  </div>
</div>`;
      this.$ = (r) => this.querySelector(`[data-r="${r}"]`);
      this.$("variable").value = this.variable;
      ["variable", "estacion", "desde", "hasta"].forEach((k) =>
        this.$(k).addEventListener("change", (e) => this.setAttribute(k, e.target.value)));
      try {
        await Promise.all([conMapa ? script(CDN.leaflet) : null, this.vista !== "mapa" ? script(CDN.plotly) : null]);
        const r = await fetch(`${this.api}/api/v1/estaciones`);
        this._geo = await r.json();
        const sel = this.$("estacion");
        sel.innerHTML = this._geo.features.map((f) => `<option value="${f.properties.clave}">${f.properties.nombre}</option>`).join("");
        if (!this.getAttribute("estacion")) this.setAttribute("estacion", this._geo.features[0].properties.clave);
        sel.value = this.getAttribute("estacion");
        if (conMapa) this.mapa();
        this._listo = true;
        this.actualizar();
      } catch (e) {
        this.querySelector(".shg").insertAdjacentHTML("beforeend", `<div class="shg-error">No se pudo iniciar el componente: ${e.message}</div>`);
      }
    }

    attributeChangedCallback(nombre) {
      if (!this._listo) return;
      if (this.$(nombre) && this.$(nombre).value !== this.getAttribute(nombre)) this.$(nombre).value = this.getAttribute(nombre) || "";
      if (nombre === "variable" && this._capa) this.pintarMapa();
      if (nombre === "estacion" && this._capa) this.pintarMapa();
      this.actualizar();
    }

    mapa() {
      const m = L.map(this.$("mapa"), { scrollWheelZoom: false });
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18, attribution: "&copy; OpenStreetMap",
      }).addTo(m);
      this._mapa = m;
      this.pintarMapa();
      m.fitBounds(this._capa.getBounds(), { padding: [20, 20] });
      setTimeout(() => m.invalidateSize(), 100);
    }

    pintarMapa() {
      if (this._capa) this._capa.remove();
      const v = this.variable, sel = this.getAttribute("estacion");
      this._capa = L.geoJSON(this._geo, {
        pointToLayer: (f, ll) => {
          const p = f.properties[`pct_faltante_${v}`];
          return L.circleMarker(ll, {
            radius: f.properties.clave === sel ? 10 : 7, weight: f.properties.clave === sel ? 3 : 1,
            color: f.properties.clave === sel ? "#111" : "#fff", fillColor: colorVacios(p), fillOpacity: .9,
          }).bindTooltip(`<b>${f.properties.nombre}</b><br>${NOMBRES[v]}: ${p.toFixed(1)}% de días sin dato<br>
            ${f.properties.altitud} m · ${f.properties.estado_operativo}`);
        },
        onEachFeature: (f, capa) => capa.on("click", () => {
          this.setAttribute("estacion", f.properties.clave);
          this.dispatchEvent(new CustomEvent("siama-estacion", { detail: { clave: f.properties.clave }, bubbles: true }));
        }),
      }).addTo(this._mapa);
    }

    async actualizar() {
      if (this.vista === "mapa") return;
      const clave = this.getAttribute("estacion"), v = this.variable;
      const q = new URLSearchParams({ variable: v });
      const token = (this._token = Symbol());
      const r = await fetch(`${this.api}/api/v1/estaciones/${clave}/serie?${q}`);
      const j = await r.json();
      if (token !== this._token) return;
      let datos = j.datos;
      let desde = this.getAttribute("desde"), hasta = this.getAttribute("hasta");
      if (!hasta) hasta = datos[datos.length - 1].fecha;
      if (!desde) { const d = new Date(hasta); d.setFullYear(d.getFullYear() - 1); desde = d.toISOString().slice(0, 10); }
      this.$("desde").value = desde; this.$("hasta").value = hasta;
      datos = datos.filter((d) => d.fecha >= desde && d.fecha <= hasta);
      this.$("titulo").textContent = `${NOMBRES[v]} · ${j.estacion.nombre}`;
      this.$("sub").textContent = `${j.estacion.municipio} · ${j.estacion.altitud} m s.n.m. · estación ${j.estacion.estado_operativo}`;
      const c = { observado: 0, estimado_alta: 0, estimado_baja: 0, no_estimable: 0 };
      datos.forEach((d) => c[d.bandera]++);
      this.$("chips").innerHTML = `
        <span class="shg-chip"><i style="background:var(--shg-observado)"></i>${c.observado} días medidos</span>
        <span class="shg-chip"><i style="background:var(--shg-estimado)"></i>${c.estimado_alta} estimados · confianza alta</span>
        <span class="shg-chip"><i style="background:var(--shg-estimado);opacity:.45"></i>${c.estimado_baja} estimados · confianza baja</span>
        <span class="shg-chip"><i style="background:#999"></i>${c.no_estimable} sin estimar</span>`;
      this.grafica(datos, v);
    }

    grafica(datos, v) {
      const u = UNIDAD[v], cs = getComputedStyle(this);
      const cObs = cs.getPropertyValue("--shg-observado").trim(), cEst = cs.getPropertyValue("--shg-estimado").trim();
      const cBanda = cs.getPropertyValue("--shg-banda").trim(), cNo = cs.getPropertyValue("--shg-noest").trim();
      const x = datos.map((d) => d.fecha);
      const esEst = datos.map((d) => d.origen === "estimado");
      const obs = datos.map((d) => d.origen === "observado" ? d.valor : null);
      const est = datos.map((d, i) => esEst[i] || esEst[i - 1] || esEst[i + 1] ? d.valor : null);
      const texto = datos.map((d) => d.origen === "estimado"
        ? `<b>Estimado</b> (confianza ${d.bandera === "estimado_alta" ? "alta" : "baja"})<br>${fmt(d.valor, u)}<br>` +
          `90% de probabilidad entre ${fmt(d.li, u)} y ${fmt(d.ls, u)}<br>Método: ${METODO[d.metodo] || d.metodo}` +
          (d.qc ? `<br>Dato original retirado por control de calidad (${d.qc})` : "")
        : d.origen === "observado" ? `<b>Medido</b><br>${fmt(d.valor, u)}` : `<b>Sin estimar</b><br>${d.motivo_no_estimable.replaceAll("_", " ")}`);
      const shapes = [];
      let ini = null;
      datos.forEach((d, i) => {
        const no = d.origen === "no_estimable";
        if (no && ini === null) ini = i;
        if ((!no || i === datos.length - 1) && ini !== null) {
          shapes.push({ type: "rect", xref: "x", yref: "paper", x0: x[ini], x1: x[no ? i : i - 1], y0: 0, y1: 1,
            fillcolor: cNo, line: { width: 0 }, layer: "below" });
          ini = null;
        }
      });
      let trazas;
      if (v === "precipitacion") {
        trazas = [
          { type: "bar", x, y: obs, name: "Medido", marker: { color: cObs }, text: texto, hoverinfo: "text+x", textposition: "none" },
          { type: "bar", x, y: datos.map((d, i) => esEst[i] ? d.valor : null), name: "Estimado",
            marker: { color: cEst, pattern: { shape: "/", fgcolor: "#fff", size: 5 } },
            error_y: { type: "data", symmetric: false, color: cEst, thickness: 1, width: 2,
              array: datos.map((d, i) => esEst[i] ? d.ls - d.valor : null),
              arrayminus: datos.map((d, i) => esEst[i] ? d.valor - d.li : null) },
            text: texto, hoverinfo: "text+x", textposition: "none" },
        ];
      } else {
        trazas = [
          { x, y: datos.map((d, i) => esEst[i] ? d.ls : null), mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false, connectgaps: false },
          { x, y: datos.map((d, i) => esEst[i] ? d.li : null), mode: "lines", line: { width: 0 }, fill: "tonexty",
            fillcolor: cBanda, name: "Rango probable (90%)", hoverinfo: "skip", connectgaps: false },
          { x, y: obs, mode: "lines", name: "Medido", line: { color: cObs, width: 1.6 }, text: texto, hoverinfo: "text+x", connectgaps: false },
          { x, y: est, mode: "lines+markers", name: "Estimado", line: { color: cEst, width: 2, dash: "dot" },
            marker: { size: 4, color: cEst }, text: texto, hoverinfo: "text+x", connectgaps: false },
        ];
      }
      if (shapes.length) trazas.push({ x: [null], y: [null], type: "bar", name: "Sin estimar", marker: { color: "rgba(120,120,120,.35)" } });
      Plotly.react(this.$("grafica"), trazas, {
        margin: { l: 48, r: 10, t: 10, b: 36 }, barmode: "overlay", bargap: 0.1,
        yaxis: { title: { text: u }, rangemode: v === "precipitacion" ? "tozero" : "normal", gridcolor: "#eef1f4" },
        xaxis: { type: "date" }, shapes, hovermode: "closest",
        legend: { orientation: "h", y: 1.12, x: 0 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
        font: { family: getComputedStyle(this).fontFamily, size: 12 },
      }, { responsive: true, displaylogo: false, locale: "es" });
    }
  }
  if (!customElements.get("siama-huecos")) customElements.define("siama-huecos", SiamaHuecos);
})();
