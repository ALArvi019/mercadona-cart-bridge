/* Panel de la cocina. Sin dependencias: la tablet solo tiene que pintar y tocar. */

const TOKEN = new URLSearchParams(location.search).get('token') || '';
const REFRESH_MS = 20000;

const $ = (id) => document.getElementById(id);
let state = { cart: [], regulars: [], pending: [] };
let filter = '';
let busy = false;

async function api(path, options = {}) {
  const url = new URL(path, location.origin);
  if (TOKEN) url.searchParams.set('token', TOKEN);
  const res = await fetch(url, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}

function toast(message, isError = false) {
  const el = $('toast');
  el.textContent = message;
  el.classList.toggle('error', isError);
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 2200);
}

function banner(message) {
  const el = $('banner');
  if (!message) { el.hidden = true; return; }
  el.textContent = message;
  el.hidden = false;
}

function money(value) {
  return typeof value === 'number' || (value && !isNaN(parseFloat(value)))
    ? `${parseFloat(value).toFixed(2).replace('.', ',')} €` : '';
}

/* ------------------------------------------------------------------ carga */

async function load(showSpinner = false) {
  if (showSpinner) $('refresh').classList.add('spin');
  try {
    state = await api('/api/state');
    banner(state.error || '');
    render();
  } catch (e) {
    banner(`Sin conexión con el servicio: ${e.message}`);
  } finally {
    $('refresh').classList.remove('spin');
  }
}

/* ---------------------------------------------------------------- pintado */

function render() {
  renderCart();
  renderRegulars();
  renderPending();
}

function renderCart() {
  const list = $('cart-list');
  list.textContent = '';
  $('cart-count').textContent = state.cart.length;
  $('cart-total').textContent = money(state.cart_total);
  $('cart-empty').hidden = state.cart.length > 0;

  for (const item of state.cart) {
    const row = document.createElement('div');
    row.className = 'row' + (item.unavailable ? ' gone' : '');

    const img = document.createElement('img');
    img.src = item.thumbnail; img.alt = ''; img.loading = 'lazy';

    const name = document.createElement('div');
    name.className = 'name';
    name.textContent = item.name;
    const sub = document.createElement('small');
    sub.textContent = [item.packaging, money(item.price)].filter(Boolean).join(' · ')
      + (item.unavailable ? ' · no disponible' : '');
    name.appendChild(sub);

    const stepper = document.createElement('div');
    stepper.className = 'stepper';
    const minus = document.createElement('button');
    minus.textContent = item.quantity > 1 ? '−' : '🗑';
    minus.onclick = () => changeQuantity(item, item.quantity - 1);
    const qty = document.createElement('span');
    qty.className = 'qty';
    qty.textContent = Number.isInteger(item.quantity) ? item.quantity : item.quantity.toFixed(1);
    const plus = document.createElement('button');
    plus.textContent = '+';
    plus.onclick = () => changeQuantity(item, item.quantity + 1);
    stepper.append(minus, qty, plus);

    row.append(img, name, stepper);
    list.appendChild(row);
  }
}

function renderRegulars() {
  const grid = $('regulars-grid');
  grid.textContent = '';
  const needle = filter.trim().toLowerCase();
  const items = needle
    ? state.regulars.filter((p) => p.name.toLowerCase().includes(needle))
    : state.regulars;

  $('regulars-empty').hidden = items.length > 0;

  for (const p of items) {
    const card = document.createElement('div');
    card.className = 'card' + (p.in_cart ? ' in-cart' : '') + (p.unavailable ? ' unavailable' : '');

    const img = document.createElement('img');
    img.src = p.thumbnail; img.alt = ''; img.loading = 'lazy';

    const name = document.createElement('div');
    name.className = 'name';
    name.textContent = p.name;

    const price = document.createElement('div');
    price.className = 'price';
    price.textContent = [money(p.price), p.packaging].filter(Boolean).join(' · ');

    const add = document.createElement('button');
    add.className = 'add';
    add.textContent = p.unavailable ? 'No disponible' : (p.in_cart ? 'Añadir otro' : 'Añadir');
    add.disabled = p.unavailable;
    add.onclick = () => addProduct(p);

    card.append(img, name, price, add);
    if (p.in_cart) {
      const badge = document.createElement('span');
      badge.className = 'badge-cart';
      badge.textContent = 'en el carrito';
      card.appendChild(badge);
    }
    grid.appendChild(card);
  }

  // Si se busca algo que no está entre los habituales, se busca en el catálogo.
  if (needle && items.length === 0) searchCatalog(needle);
}

let searchTimer = null;
function searchCatalog(query) {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    try {
      const results = await api(`/api/search?q=${encodeURIComponent(query)}`);
      if (filter.trim().toLowerCase() !== query) return;   // ya se escribió otra cosa
      const grid = $('regulars-grid');
      grid.textContent = '';
      $('regulars-empty').hidden = results.length > 0;
      const inCart = new Set(state.cart.map((c) => c.id));
      for (const p of results) {
        grid.appendChild(cardFor({ ...p, in_cart: inCart.has(p.id) }));
      }
    } catch (e) { /* la búsqueda es accesoria: no molestamos si falla */ }
  }, 250);
}

function cardFor(p) {
  const card = document.createElement('div');
  card.className = 'card' + (p.in_cart ? ' in-cart' : '') + (p.unavailable ? ' unavailable' : '');
  const img = document.createElement('img');
  img.src = p.thumbnail; img.alt = ''; img.loading = 'lazy';
  const name = document.createElement('div');
  name.className = 'name'; name.textContent = p.name;
  const price = document.createElement('div');
  price.className = 'price'; price.textContent = [money(p.price), p.packaging].filter(Boolean).join(' · ');
  const add = document.createElement('button');
  add.className = 'add'; add.textContent = p.unavailable ? 'No disponible' : 'Añadir';
  add.disabled = !!p.unavailable;
  add.onclick = () => addProduct(p);
  card.append(img, name, price, add);
  return card;
}

function renderPending() {
  const bar = $('pending-bar');
  bar.textContent = '';
  const items = state.pending || [];
  bar.hidden = items.length === 0;

  for (const entry of items) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    const label = document.createElement('span');
    label.innerHTML = 'No sé qué es ';
    const strong = document.createElement('b');
    strong.textContent = `“${entry.phrase}”`;
    label.appendChild(strong);

    const choose = document.createElement('button');
    choose.textContent = 'Elegir';
    choose.onclick = () => openChooser(entry);

    const drop = document.createElement('button');
    drop.className = 'ghost';
    drop.textContent = 'Descartar';
    drop.onclick = async () => {
      await api(`/api/pending/${entry.id}`, { method: 'DELETE' });
      load();
    };

    chip.append(label, choose, drop);
    bar.appendChild(chip);
  }
}

/* ------------------------------------------------------------- acciones */

async function addProduct(p) {
  if (busy) return;
  busy = true;
  try {
    await api('/api/cart/add', {
      method: 'POST',
      body: JSON.stringify({ product_id: p.id, quantity: 1 }),
    });
    toast(`Añadido: ${p.name}`);
    await load();
  } catch (e) {
    toast(`No se pudo añadir: ${e.message}`, true);
  } finally {
    busy = false;
  }
}

async function changeQuantity(item, quantity) {
  if (busy) return;
  busy = true;
  try {
    await api('/api/cart/quantity', {
      method: 'POST',
      body: JSON.stringify({ product_id: item.id, quantity: Math.max(0, quantity) }),
    });
    toast(quantity <= 0 ? `Quitado: ${item.name}` : `${item.name}: ${quantity}`);
    await load();
  } catch (e) {
    toast(`No se pudo actualizar: ${e.message}`, true);
  } finally {
    busy = false;
  }
}

/* Elegir producto para una frase que el sistema no supo resolver. */
async function openChooser(entry) {
  let results = [];
  try {
    results = await api(`/api/search?q=${encodeURIComponent(entry.phrase)}&limit=12`);
  } catch (e) {
    toast(`No se pudo buscar: ${e.message}`, true);
    return;
  }

  const back = document.createElement('div');
  back.className = 'modal-back';
  back.onclick = (ev) => { if (ev.target === back) back.remove(); };

  const modal = document.createElement('div');
  modal.className = 'modal';
  const title = document.createElement('h2');
  title.textContent = `¿Qué es “${entry.phrase}”?`;

  const list = document.createElement('div');
  list.className = 'list';
  for (const p of results) {
    const row = document.createElement('div');
    row.className = 'row';
    const img = document.createElement('img');
    img.src = p.thumbnail; img.alt = '';
    const name = document.createElement('div');
    name.className = 'name';
    name.textContent = p.name;
    const sub = document.createElement('small');
    sub.textContent = [p.packaging, money(p.price)].filter(Boolean).join(' · ');
    name.appendChild(sub);
    row.append(img, name);
    row.onclick = async () => {
      try {
        await api(`/api/pending/${entry.id}/resolve`, {
          method: 'POST',
          body: JSON.stringify({ product_id: p.id, remember: true }),
        });
        toast(`Añadido: ${p.name}. La próxima vez lo sabré.`);
        back.remove();
        load();
      } catch (e) {
        toast(`No se pudo añadir: ${e.message}`, true);
      }
    };
    list.appendChild(row);
  }
  if (!results.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = 'No encuentro nada parecido en el catálogo.';
    list.appendChild(empty);
  }

  const footer = document.createElement('footer');
  const close = document.createElement('button');
  close.textContent = 'Cerrar';
  close.onclick = () => back.remove();
  footer.appendChild(close);

  modal.append(title, list, footer);
  back.appendChild(modal);
  document.body.appendChild(back);
}

/* ---------------------------------------------------------------- arranque */

$('search').addEventListener('input', (e) => { filter = e.target.value; renderRegulars(); });
$('refresh').addEventListener('click', () => load(true));

load(true);
setInterval(() => { if (!document.hidden && !busy) load(); }, REFRESH_MS);
document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
