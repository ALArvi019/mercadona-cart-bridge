/* Panel de la compra dentro de Home Assistant.
 *
 * Es la misma interfaz que servía el contenedor. Lo único que cambia es de dónde
 * salen los datos: en vez de llamar a FastAPI con un token en la URL, usa el objeto
 * `hass` que Home Assistant inyecta en el panel, que ya viene autenticado.
 */

const REFRESH_MS = 20000;

class MercadonaPanel extends HTMLElement {
  static get properties() {
    return { hass: {}, narrow: {}, route: {}, panel: {} };
  }

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._state = { cart: [], regulars: [], cart_total: null };
    this._filter = '';
    this._busy = false;
    this._timer = null;
    this._rendered = false;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._build();
      this._load();
    }
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    this._timer = setInterval(() => {
      if (!document.hidden && !this._busy) this._load();
    }, REFRESH_MS);
  }

  disconnectedCallback() {
    if (this._timer) clearInterval(this._timer);
  }

  /* ------------------------------------------------------------ estructura */

  _build() {
    if (this._rendered) return;
    this._rendered = true;
    this.shadowRoot.innerHTML = `
      <link rel="stylesheet" href="/mercadona_panel/style.css">
      <div id="banner" class="banner" hidden></div>
      <main class="layout">
        <section class="pane">
          <header class="pane-head">
            <h1>En el carrito <span id="cart-count" class="count">0</span></h1>
            <div class="head-right">
              <span id="cart-total" class="total"></span>
              <button id="refresh" class="icon-btn" title="Actualizar">&#10227;</button>
            </div>
          </header>
          <div id="cart-list" class="list"></div>
          <p id="cart-empty" class="empty" hidden>El carrito está vacío.<br><small>Pide algo a Google o toca un habitual.</small></p>
        </section>
        <section class="pane">
          <header class="pane-head">
            <h1>Habituales</h1>
            <input id="search" type="search" placeholder="Buscar producto…" autocomplete="off">
          </header>
          <div id="regulars-grid" class="grid"></div>
          <p id="regulars-empty" class="empty" hidden>Sin resultados.</p>
        </section>
      </main>
      <div id="toast" class="toast" hidden></div>
    `;

    this.$('#search').addEventListener('input', (e) => {
      this._filter = e.target.value;
      this._renderRegulars();
    });
    this.$('#refresh').addEventListener('click', () => this._load(true));
  }

  $(sel) {
    return this.shadowRoot.querySelector(sel);
  }

  /* ----------------------------------------------------------------- datos */

  async _api(method, path, body) {
    return this.hass.callApi(method, `mercadona/${path}`, body);
  }

  async _load(spin = false) {
    if (spin) this.$('#refresh').classList.add('spin');
    try {
      this._state = await this._api('GET', 'state');
      this._banner(this._state.ok ? '' : 'Home Assistant no puede leer el carrito de Mercadona.');
      this._render();
    } catch (err) {
      this._banner(`No se pudo leer el carrito: ${err.message || err}`);
    } finally {
      this.$('#refresh').classList.remove('spin');
    }
  }

  _banner(message) {
    const el = this.$('#banner');
    if (!message) { el.hidden = true; return; }
    el.textContent = message;
    el.hidden = false;
  }

  _toast(message, isError = false) {
    const el = this.$('#toast');
    el.textContent = message;
    el.classList.toggle('error', isError);
    el.hidden = false;
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 2200);
  }

  _money(value) {
    const n = parseFloat(value);
    return isNaN(n) ? '' : `${n.toFixed(2).replace('.', ',')} €`;
  }

  /* --------------------------------------------------------------- pintado */

  _render() {
    this._renderCart();
    this._renderRegulars();
  }

  _renderCart() {
    const list = this.$('#cart-list');
    list.textContent = '';
    this.$('#cart-count').textContent = this._state.cart.length;
    this.$('#cart-total').textContent = this._money(this._state.cart_total);
    this.$('#cart-empty').hidden = this._state.cart.length > 0;

    for (const item of this._state.cart) {
      const row = document.createElement('div');
      row.className = 'row' + (item.unavailable ? ' gone' : '');

      const img = document.createElement('img');
      img.src = item.thumbnail; img.alt = ''; img.loading = 'lazy';

      const name = document.createElement('div');
      name.className = 'name';
      name.textContent = item.name;
      const sub = document.createElement('small');
      sub.textContent = [item.packaging, this._money(item.price)].filter(Boolean).join(' · ')
        + (item.unavailable ? ' · no disponible' : '');
      name.appendChild(sub);

      const stepper = document.createElement('div');
      stepper.className = 'stepper';
      const minus = document.createElement('button');
      minus.textContent = item.quantity > 1 ? '−' : '🗑';
      minus.onclick = () => this._setQuantity(item, item.quantity - 1);
      const qty = document.createElement('span');
      qty.className = 'qty';
      qty.textContent = Number.isInteger(item.quantity) ? item.quantity : item.quantity.toFixed(1);
      const plus = document.createElement('button');
      plus.textContent = '+';
      plus.onclick = () => this._setQuantity(item, item.quantity + 1);
      stepper.append(minus, qty, plus);

      row.append(img, name, stepper);
      list.appendChild(row);
    }
  }

  _card(p) {
    const card = document.createElement('div');
    card.className = 'card' + (p.in_cart ? ' in-cart' : '') + (p.unavailable ? ' unavailable' : '');
    const img = document.createElement('img');
    img.src = p.thumbnail; img.alt = ''; img.loading = 'lazy';
    const name = document.createElement('div');
    name.className = 'name'; name.textContent = p.name;
    const price = document.createElement('div');
    price.className = 'price';
    price.textContent = [this._money(p.price), p.packaging].filter(Boolean).join(' · ');
    const add = document.createElement('button');
    add.className = 'add';
    add.textContent = p.unavailable ? 'No disponible' : (p.in_cart ? 'Añadir otro' : 'Añadir');
    add.disabled = !!p.unavailable;
    add.onclick = () => this._add(p);
    card.append(img, name, price, add);
    if (p.in_cart) {
      const badge = document.createElement('span');
      badge.className = 'badge-cart';
      badge.textContent = 'en el carrito';
      card.appendChild(badge);
    }
    return card;
  }

  _renderRegulars() {
    const grid = this.$('#regulars-grid');
    grid.textContent = '';
    const needle = this._filter.trim().toLowerCase();
    const items = needle
      ? this._state.regulars.filter((p) => p.name.toLowerCase().includes(needle))
      : this._state.regulars;

    this.$('#regulars-empty').hidden = items.length > 0;
    for (const p of items) grid.appendChild(this._card(p));

    // Si no está entre los habituales, se busca en el catálogo del almacén.
    if (needle && items.length === 0) this._search(needle);
  }

  _search(query) {
    clearTimeout(this._searchTimer);
    this._searchTimer = setTimeout(async () => {
      try {
        const results = await this._api('GET', `search?q=${encodeURIComponent(query)}`);
        if (this._filter.trim().toLowerCase() !== query) return;
        const grid = this.$('#regulars-grid');
        grid.textContent = '';
        this.$('#regulars-empty').hidden = results.length > 0;
        const inCart = new Set(this._state.cart.map((c) => c.id));
        for (const p of results) grid.appendChild(this._card({ ...p, in_cart: inCart.has(p.id) }));
      } catch (err) { /* la búsqueda es accesoria */ }
    }, 250);
  }

  /* -------------------------------------------------------------- acciones */

  async _add(product) {
    if (this._busy) return;
    this._busy = true;
    try {
      await this._api('POST', 'cart', { product_id: product.id, add: 1 });
      this._toast(`Añadido: ${product.name}`);
      await this._load();
    } catch (err) {
      this._toast(`No se pudo añadir: ${err.message || err}`, true);
    } finally {
      this._busy = false;
    }
  }

  async _setQuantity(item, quantity) {
    if (this._busy) return;
    this._busy = true;
    try {
      await this._api('POST', 'cart', { product_id: item.id, quantity: Math.max(0, quantity) });
      this._toast(quantity <= 0 ? `Quitado: ${item.name}` : `${item.name}: ${quantity}`);
      await this._load();
    } catch (err) {
      this._toast(`No se pudo actualizar: ${err.message || err}`, true);
    } finally {
      this._busy = false;
    }
  }
}

customElements.define('mercadona-panel', MercadonaPanel);
