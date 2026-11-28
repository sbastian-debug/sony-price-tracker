let priceChart = null;
let stockChart = null;
let currentProducts = [];
let debounceTimer = null;
let syncPollInterval = null;
let viewMode = localStorage.getItem('sony_view_mode') === 'list' ? 'list' : 'grid';

// Fallback SVG seguro integrado localmente (sin depender de dominios externos)
const FALLBACK_PRODUCT_IMG =
    "data:image/svg+xml;charset=UTF-8," +
    encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="260" height="260" viewBox="0 0 260 260">' +
        '<rect width="260" height="260" rx="24" fill="#0d1424"/>' +
        '<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" ' +
        'fill="#64748b" font-family="sans-serif" font-size="22" font-weight="700">SONY</text></svg>'
    );

const FALLBACK_CAMPAIGN_IMG =
    "data:image/svg+xml;charset=UTF-8," +
    encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200" viewBox="0 0 400 200">' +
        '<rect width="400" height="200" fill="#0d1424"/>' +
        '<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" ' +
        'fill="#64748b" font-family="sans-serif" font-size="20" font-weight="700">Campaña Sony</text></svg>'
    );

document.addEventListener('DOMContentLoaded', () => {
    bindEventListeners();
    updateViewSwitchButtons();
    loadCategories();
    loadCollections();
    applyFilters();
    updateGlobalStats();
    loadCampaigns();
});

function bindEventListeners() {
    const tabProductsBtn = document.getElementById('tab-products-btn');
    const tabCampaignsBtn = document.getElementById('tab-campaigns-btn');
    const syncBtn = document.getElementById('sync-btn');
    const searchInput = document.getElementById('search-input');
    const stockSelect = document.getElementById('stock-select');
    const categorySelect = document.getElementById('category-select');
    const collectionSelect = document.getElementById('collection-select');
    const sortSelect = document.getElementById('sort-select');
    const onlyMinCheckbox = document.getElementById('only-min-checkbox');
    const onlyPromoCheckbox = document.getElementById('only-promo-checkbox');
    const viewGridBtn = document.getElementById('view-grid-btn');
    const viewListBtn = document.getElementById('view-list-btn');
    const productsContainer = document.getElementById('products-container');
    const campaignsGrid = document.getElementById('campaigns-grid');
    const modalBannersList = document.getElementById('modal-banners-list');
    const priceModal = document.getElementById('price-modal');
    const priceModalCloseBtn = document.getElementById('price-modal-close-btn');
    const campaignModal = document.getElementById('campaign-modal');
    const campaignModalCloseBtn = document.getElementById('campaign-modal-close-btn');

    if (tabProductsBtn) tabProductsBtn.addEventListener('click', () => switchTab('products'));
    if (tabCampaignsBtn) tabCampaignsBtn.addEventListener('click', () => switchTab('campaigns'));
    if (syncBtn) syncBtn.addEventListener('click', triggerSync);

    if (searchInput) searchInput.addEventListener('input', applyFiltersDebounced);
    if (categorySelect) categorySelect.addEventListener('change', applyFilters);
    if (collectionSelect) collectionSelect.addEventListener('change', applyFilters);
    if (onlyMinCheckbox) onlyMinCheckbox.addEventListener('change', applyFilters);
    if (onlyPromoCheckbox) onlyPromoCheckbox.addEventListener('change', applyFilters);

    if (stockSelect) {
        stockSelect.addEventListener('change', () => {
            const val = stockSelect.value;
            if ((val === 'out_of_stock' || val === 'just_exhausted') && onlyMinCheckbox) {
                onlyMinCheckbox.checked = false;
            }
            if (sortSelect) {
                if (val === 'just_exhausted') {
                    sortSelect.value = 'just_exhausted';
                } else if (val === 'restocked') {
                    sortSelect.value = 'restocked';
                } else if (sortSelect.value === 'just_exhausted' || sortSelect.value === 'restocked') {
                    sortSelect.value = 'discount_desc';
                }
            }
            applyFilters();
        });
    }

    if (sortSelect) {
        sortSelect.addEventListener('change', () => {
            const val = sortSelect.value;
            if (stockSelect) {
                if (val === 'just_exhausted') {
                    stockSelect.value = 'just_exhausted';
                    if (onlyMinCheckbox) onlyMinCheckbox.checked = false;
                } else if (val === 'restocked') {
                    stockSelect.value = 'restocked';
                } else if (stockSelect.value === 'just_exhausted' || stockSelect.value === 'restocked') {
                    stockSelect.value = 'in_stock';
                }
            }
            applyFilters();
        });
    }

    if (viewGridBtn) viewGridBtn.addEventListener('click', () => setViewMode('grid'));
    if (viewListBtn) viewListBtn.addEventListener('click', () => setViewMode('list'));

    // Delegación segura de eventos para productos y manejo de imágenes rotas (sin handlers inline)
    if (productsContainer) {
        productsContainer.addEventListener('click', (e) => {
            const target = e.target.closest('[data-prod-id]');
            if (target && target.dataset.prodId) {
                openPriceModal(target.dataset.prodId);
            }
        });
        productsContainer.addEventListener('error', (e) => {
            if (e.target && e.target.tagName === 'IMG' && !e.target.dataset.fallbackApplied) {
                e.target.dataset.fallbackApplied = '1';
                e.target.src = FALLBACK_PRODUCT_IMG;
            }
        }, true);
    }

    if (campaignsGrid) {
        campaignsGrid.addEventListener('click', (e) => {
            const card = e.target.closest('[data-camp-id]');
            if (card && card.dataset.campId) {
                openCampaignModal(Number(card.dataset.campId));
            }
        });
        campaignsGrid.addEventListener('error', (e) => {
            if (e.target && e.target.tagName === 'IMG' && !e.target.dataset.fallbackApplied) {
                e.target.dataset.fallbackApplied = '1';
                e.target.src = FALLBACK_CAMPAIGN_IMG;
            }
        }, true);
    }

    if (modalBannersList) {
        modalBannersList.addEventListener('error', (e) => {
            if (e.target && e.target.tagName === 'IMG' && !e.target.dataset.fallbackApplied) {
                e.target.dataset.fallbackApplied = '1';
                e.target.src = FALLBACK_CAMPAIGN_IMG;
            }
        }, true);
    }

    if (priceModalCloseBtn) priceModalCloseBtn.addEventListener('click', closePriceModal);
    if (priceModal) {
        priceModal.addEventListener('click', (e) => {
            if (e.target === priceModal) closePriceModal();
        });
    }

    if (campaignModalCloseBtn) campaignModalCloseBtn.addEventListener('click', closeCampaignModal);
    if (campaignModal) {
        campaignModal.addEventListener('click', (e) => {
            if (e.target === campaignModal) closeCampaignModal();
        });
    }

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closePriceModal();
            closeCampaignModal();
        }
    });
}

// Sanitizar URLs para bloquear esquemas inseguros (javascript:, data:, etc.)
function sanitizeUrl(url, allowLocalBanner = false) {
    if (!url || typeof url !== 'string') return '';
    const trimmed = url.trim();
    if (allowLocalBanner && trimmed.startsWith('/data/banners/') && !trimmed.includes('..') && !trimmed.includes('\\')) {
        return trimmed;
    }
    try {
        const parsed = new URL(trimmed, window.location.origin);
        if (parsed.protocol === 'https:' || parsed.protocol === 'http:') {
            return parsed.href;
        }
    } catch (_) {
        return '';
    }
    return '';
}

async function fetchJsonSafe(url, options = {}) {
    const res = await fetch(url, options);
    let payload = null;
    try {
        payload = await res.json();
    } catch (_) {
        payload = null;
    }
    if (!res.ok) {
        const msg = (payload && payload.error) ? payload.error : `Error HTTP ${res.status}`;
        throw new Error(msg);
    }
    return payload;
}

// Cambiar de modo de vista (Cuadrícula con Fotos Grandes vs Lista)
function setViewMode(mode) {
    viewMode = mode === 'list' ? 'list' : 'grid';
    localStorage.setItem('sony_view_mode', viewMode);
    updateViewSwitchButtons();
    renderProducts(currentProducts);
}

function updateViewSwitchButtons() {
    const gridBtn = document.getElementById('view-grid-btn');
    const listBtn = document.getElementById('view-list-btn');
    if (!gridBtn || !listBtn) return;

    if (viewMode === 'grid') {
        gridBtn.classList.add('active');
        listBtn.classList.remove('active');
    } else {
        listBtn.classList.add('active');
        gridBtn.classList.remove('active');
    }
}

// Cambiar entre Pestañas: Catálogo y Campañas
function switchTab(tab) {
    const productsView = document.getElementById('view-products');
    const campaignsView = document.getElementById('view-campaigns');
    const tabProductsBtn = document.getElementById('tab-products-btn');
    const tabCampaignsBtn = document.getElementById('tab-campaigns-btn');

    if (productsView) productsView.classList.remove('active');
    if (campaignsView) campaignsView.classList.remove('active');
    if (tabProductsBtn) tabProductsBtn.classList.remove('active');
    if (tabCampaignsBtn) tabCampaignsBtn.classList.remove('active');

    if (tab === 'products') {
        if (productsView) productsView.classList.add('active');
        if (tabProductsBtn) tabProductsBtn.classList.add('active');
    } else if (tab === 'campaigns') {
        if (campaignsView) campaignsView.classList.add('active');
        if (tabCampaignsBtn) tabCampaignsBtn.classList.add('active');
        loadCampaigns();
    }
}

// Formatear moneda en Bolivianos
function formatBs(amount) {
    if (amount === undefined || amount === null || isNaN(amount)) return 'Bs. 0';
    return `Bs. ${Number(amount).toLocaleString('es-BO', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
}

function formatShortTimestamp(ts) {
    if (!ts || typeof ts !== 'string') return '';
    const parts = ts.trim().split(' ');
    const dateParts = (parts[0] || '').split('-');
    if (dateParts.length === 3) {
        const dayMonth = `${dateParts[2]}/${dateParts[1]}`;
        const timePart = parts[1] ? parts[1].slice(0, 5) : '';
        return timePart ? `${dayMonth} ${timePart}` : dayMonth;
    }
    return ts;
}

// Cargar categorías en el selector de filtros
async function loadCategories() {
    try {
        const categories = await fetchJsonSafe('/api/categories');
        const select = document.getElementById('category-select');
        if (!select || !Array.isArray(categories)) return;
        const prevValue = select.value || 'Todas';
        select.innerHTML = '<option value="Todas">Todas las Categorías</option>';
        categories.forEach(cat => {
            const opt = document.createElement('option');
            opt.value = cat;
            opt.textContent = cat;
            select.appendChild(opt);
        });
        if ([...select.options].some(o => o.value === prevValue)) {
            select.value = prevValue;
        }
    } catch (e) {
        console.error('Error cargando categorías:', e);
    }
}

// Cargar colecciones / campañas internas en el selector de filtros
async function loadCollections() {
    try {
        const collections = await fetchJsonSafe('/api/collections');
        const select = document.getElementById('collection-select');
        if (!select || !Array.isArray(collections)) return;
        const prevValue = select.value || 'Todas';
        select.innerHTML = '<option value="Todas">Todas las Colecciones</option>';
        collections.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.nombre;
            opt.textContent = `${c.nombre} (${c.total})`;
            select.appendChild(opt);
        });
        if ([...select.options].some(o => o.value === prevValue)) {
            select.value = prevValue;
        }
    } catch (e) {
        console.error('Error cargando colecciones:', e);
    }
}

// Aplicar filtros con debounce
function applyFiltersDebounced() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
        applyFilters();
    }, 280);
}

function applyFilters() {
    const q = document.getElementById('search-input') ? document.getElementById('search-input').value.trim() : '';
    const cat = document.getElementById('category-select') ? document.getElementById('category-select').value : 'Todas';
    const col = document.getElementById('collection-select') ? document.getElementById('collection-select').value : 'Todas';
    const onlyMin = document.getElementById('only-min-checkbox') ? document.getElementById('only-min-checkbox').checked : false;
    const onlyPromo = document.getElementById('only-promo-checkbox') ? document.getElementById('only-promo-checkbox').checked : false;
    const sort = document.getElementById('sort-select') ? document.getElementById('sort-select').value : 'discount_desc';
    const stock = document.getElementById('stock-select') ? document.getElementById('stock-select').value : 'in_stock';

    const params = new URLSearchParams({
        q: q,
        category: cat,
        collection: col,
        only_min: onlyMin,
        only_promo: onlyPromo,
        sort: sort,
        stock: stock
    });

    loadProducts(params.toString());
}

// Actualizar barra de métricas globales
async function updateGlobalStats() {
    try {
        const allProds = await fetchJsonSafe('/api/products?stock=all');
        if (!Array.isArray(allProds)) return;

        const inStock = allProds.filter(p => p.disponible === 1 && p.stock > 0 && p.precio_actual > 0);
        const outOfStock = allProds.filter(p => p.disponible === 0 || p.stock === 0 || p.precio_actual === 0);
        const minHistory = inStock.filter(p => p.es_minimo_historico === 1);

        const elTotal = document.getElementById('stat-total-products');
        const elInStock = document.getElementById('stat-in-stock');
        const elOutOfStock = document.getElementById('stat-out-of-stock');
        const elMinPrices = document.getElementById('stat-min-prices');

        if (elTotal) elTotal.textContent = allProds.length;
        if (elInStock) elInStock.textContent = inStock.length;
        if (elOutOfStock) elOutOfStock.textContent = outOfStock.length;
        if (elMinPrices) elMinPrices.textContent = minHistory.length;
    } catch (e) {
        console.error('Error calculando métricas globales:', e);
    }
}

// Cargar productos desde la API
async function loadProducts(queryString = 'stock=in_stock&sort=discount_desc') {
    const container = document.getElementById('products-container');
    if (!container) return;

    container.className = 'products-cards-grid';
    container.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 60px; color: var(--text-secondary);">
            <i class="ph-bold ph-spinner spinner" style="font-size: 32px; color: var(--accent-cyan); display:block; margin-bottom: 12px;"></i>
            Cargando catálogo con Liquid Glass UI...
        </div>
    `;

    try {
        const products = await fetchJsonSafe(`/api/products?${queryString}`);
        if (!Array.isArray(products)) {
            throw new Error('Respuesta inesperada de la API de productos');
        }
        currentProducts = products;
        renderProducts(products);
    } catch (e) {
        console.error('Error cargando productos:', e);
        container.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; color: var(--accent-rose); padding: 40px;">
                Error al conectar con la base de datos local: ${escapeHtml(e.message)}
            </div>
        `;
    }
}

// Selecciona hasta N colecciones destacadas visibles por tarjeta (excluye genéricas 'todos'/'despacho')
const FEATURED_COLLECTIONS = new Set([
    'blackfriday', 'campana-camaras', 'nuevo', 'secret-sale', 'liquidacion', 'flash-sale'
]);

function getDisplayCollections(cols) {
    if (!Array.isArray(cols)) return [];
    const filtered = cols
        .map(c => (c && c.name ? String(c.name).trim() : ''))
        .filter(n => n && !['todos', 'despacho'].includes(n.toLowerCase()));
    filtered.sort((a, b) => {
        const aFeat = FEATURED_COLLECTIONS.has(a.toLowerCase()) ? 0 : 1;
        const bFeat = FEATURED_COLLECTIONS.has(b.toLowerCase()) ? 0 : 1;
        return aFeat - bFeat;
    });
    return [...new Set(filtered)];
}

function getCollectionChipClass(name) {
    const low = String(name || '').toLowerCase();
    if (['campana-camaras', 'secret-sale', 'cupon-fest', 'hitdelmes', 'exclusivo-ss', 'kits-especiales'].includes(low)) {
        return 'col-chip col-special';
    }
    if (['blackfriday', 'liquidacion', 'flash-sale', 'blackweek', 'venta-nocturna', 'hot-sale'].includes(low)) {
        return 'col-chip col-sale';
    }
    return 'col-chip';
}

// Renderizar productos según la vista seleccionada (Fotos Grandes vs Tabla)
function renderProducts(products) {
    const container = document.getElementById('products-container');
    if (!container) return;

    const sortSelect = document.getElementById('sort-select');
    const stockSelect = document.getElementById('stock-select');
    const isPriceChangedFilter = sortSelect && sortSelect.value === 'price_changed';
    const isJustExhaustedFilter = (sortSelect && sortSelect.value === 'just_exhausted') || (stockSelect && stockSelect.value === 'just_exhausted');
    const isRestockedFilter = (sortSelect && sortSelect.value === 'restocked') || (stockSelect && stockSelect.value === 'restocked');

    if (!products || products.length === 0) {
        let emptyMsg = 'No se encontraron productos con los filtros seleccionados.';
        let emptyIcon = 'ph-ghost';
        if (isPriceChangedFilter) {
            emptyMsg = 'No se encontraron artículos con cambios de precio en la última sincronización.';
            emptyIcon = 'ph-bell-slash';
        } else if (isJustExhaustedFilter) {
            emptyMsg = 'No se encontraron artículos que se hayan agotado recientemente.';
            emptyIcon = 'ph-package';
        } else if (isRestockedFilter) {
            emptyMsg = 'No se encontraron artículos que hayan vuelto a tener stock recientemente.';
            emptyIcon = 'ph-sparkle';
        }

        container.className = 'products-cards-grid';
        container.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 60px; color: var(--text-secondary); width: 100%;">
                <i class="ph-bold ${emptyIcon}" style="font-size: 40px; display: block; margin-bottom: 12px; color: var(--accent-cyan);"></i>
                ${escapeHtml(emptyMsg)}
            </div>
        `;
        return;
    }

    if (viewMode === 'grid') {
        container.className = 'products-cards-grid';
        container.innerHTML = products.map(p => {
            const safeId = escapeHtml(String(p.id || ''));
            const safeImg = escapeHtml(sanitizeUrl(p.imagen_url, false) || FALLBACK_PRODUCT_IMG);
            const inStock = p.disponible === 1 && Number(p.stock) > 0 && Number(p.precio_actual) > 0;
            const discountPct = Number(p.descuento_porcentaje) || 0;
            const hasDiscount = inStock && discountPct > 0 && Number(p.precio_lista) > Number(p.precio_actual);
            const isMin = inStock && p.es_minimo_historico === 1;

            const hasPriceChange = p.cambio_reciente === 1 && Number(p.diferencia_precio) !== 0 && Number(p.precio_anterior) > 0;
            const isPriceDrop = hasPriceChange && Number(p.diferencia_precio) < 0;
            const isPriceRise = hasPriceChange && Number(p.diferencia_precio) > 0;

            const isJustExhausted = p.recien_agotado === 1;
            const isRestocked = p.recien_reabastecido === 1;
            const stockQty = Math.max(0, Number(p.stock) || 0);
            const isLowStock = inStock && stockQty > 0 && stockQty <= 3;

            const teasers = Array.isArray(p.teasers) ? p.teasers : [];
            const regalos = Array.isArray(p.regalos) ? p.regalos : [];
            const buyTogether = Array.isArray(p.buy_together) ? p.buy_together : [];
            const highlights = Array.isArray(p.highlights) ? p.highlights : [];
            const isNewHighlight = highlights.some(h => String(h.name || '').toLowerCase() === 'nuevo');
            const displayCols = getDisplayCollections(p.colecciones).slice(0, 3);

            let priceBlock = '';
            if (inStock) {
                if (hasPriceChange) {
                    priceBlock = `
                        <div class="price-stack">
                            <span class="price-strike-liquid">Antes: ${formatBs(p.precio_anterior)}</span>
                            <span class="price-current-liquid ${isPriceDrop ? 'text-emerald' : 'text-amber'}">${formatBs(p.precio_actual)}</span>
                        </div>
                    `;
                } else {
                    priceBlock = `
                        <div class="price-stack">
                            ${hasDiscount ? `<span class="price-strike-liquid">${formatBs(p.precio_lista)}</span>` : ''}
                            <span class="price-current-liquid ${isMin ? 'text-emerald' : ''}">${formatBs(p.precio_actual)}</span>
                        </div>
                    `;
                }
            } else {
                if (Number(p.precio_actual) > 0) {
                    priceBlock = `
                        <div class="price-stack">
                            <span class="price-out-of-stock">${formatBs(p.precio_actual)}</span>
                            <span class="stock-out-label"><i class="ph-bold ph-x-circle"></i> Agotado / Sin Stock</span>
                        </div>
                    `;
                } else {
                    priceBlock = `
                        <div class="price-stack">
                            <span class="price-unavailable">Sin Stock / No disponible</span>
                        </div>
                    `;
                }
            }

            return `
                <div class="product-hero-card ${inStock ? '' : 'is-out-of-stock'}">
                    <div class="card-img-stage" data-prod-id="${safeId}">
                        <img src="${safeImg}" 
                             alt="${escapeHtml(p.nombre)}" 
                             class="card-hero-img" 
                             loading="lazy">

                        ${inStock && hasDiscount ? `
                            <span class="badge-discount-float">-${escapeHtml(discountPct)}%</span>
                        ` : ''}

                        <div class="card-badges-top-left">
                            ${isRestocked ? `
                                <span class="badge-restocked-float" title="¡Este producto volvió a tener stock disponible en Sony!">
                                    <i class="ph-bold ph-arrow-counter-clockwise"></i> ¡Volvió a Tener Stock!
                                </span>
                            ` : (isJustExhausted ? `
                                <span class="badge-just-exhausted-float" title="Se quedó sin stock en Sony">
                                    <i class="ph-bold ph-warning"></i> ¡Recién Agotado!
                                </span>
                            ` : (!inStock ? `
                                <span class="badge-stock-out-float">
                                    <i class="ph-bold ph-x-circle"></i> Agotado
                                </span>
                            ` : ''))}

                            ${isMin ? `
                                <span class="badge-min-low-float" title="Precio actual es el más bajo registrado en Sony Bolivia">
                                    <i class="ph-bold ph-star"></i> Mínimo Histórico
                                </span>
                            ` : ''}

                            ${isLowStock ? `
                                <span class="badge-stock-low-float" title="Quedan muy pocas unidades en inventario">
                                    <i class="ph-bold ph-lightning"></i> ¡Últimas ${stockQty} unid.!
                                </span>
                            ` : ''}

                            ${isNewHighlight ? `
                                <span class="badge-new-cluster-float" title="Producto marcado como Nuevo en Sony Store">
                                    <i class="ph-bold ph-sparkle"></i> Nuevo
                                </span>
                            ` : ''}

                            ${regalos.length > 0 ? `
                                <span class="badge-gift-float" title="Incluye regalo gratis con tu compra">
                                    <i class="ph-bold ph-gift"></i> ¡Regalo Incluido!
                                </span>
                            ` : ''}

                            ${teasers.length > 0 ? `
                                <span class="badge-promo-float" title="${escapeHtml(teasers[0].name)}">
                                    <i class="ph-bold ph-tag"></i> ${escapeHtml(teasers[0].name)}
                                </span>
                            ` : (buyTogether.length > 0 ? `
                                <span class="badge-promo-float" title="Tiene sugerencia BuyTogether activa">
                                    <i class="ph-bold ph-handshake"></i> Combo Sugerido
                                </span>
                            ` : '')}
                        </div>

                        ${isPriceDrop ? `
                            <span class="badge-price-drop-float" title="Precio rebajado recientemente">
                                <i class="ph-bold ph-trend-down"></i> Bajó ${formatBs(Math.abs(p.diferencia_precio))} (${escapeHtml(p.porcentaje_cambio_precio)}%)
                            </span>
                        ` : ''}

                        ${isPriceRise ? `
                            <span class="badge-price-rise-float" title="Precio aumentado recientemente">
                                <i class="ph-bold ph-trend-up"></i> Subió ${formatBs(p.diferencia_precio)} (+${escapeHtml(p.porcentaje_cambio_precio)}%)
                            </span>
                        ` : ''}
                    </div>

                    <div class="card-details">
                        <div class="card-cat-row">
                            <span class="glass-badge badge-accent">${escapeHtml(p.categoria || 'General')}</span>
                            ${inStock ? `
                                <span class="badge-stock-pill ${isLowStock ? 'stock-low' : 'stock-plenty'}">
                                    <i class="ph-bold ${isLowStock ? 'ph-lightning' : 'ph-package'}"></i> Stock: ${stockQty} unid.
                                </span>
                            ` : `
                                <span class="badge-stock-pill stock-zero">
                                    <i class="ph-bold ph-x-circle"></i> Stock: 0
                                </span>
                            `}
                        </div>

                        <h3 class="card-title" title="${escapeHtml(p.nombre)}" data-prod-id="${safeId}">
                            ${escapeHtml(p.nombre)}
                        </h3>

                        ${displayCols.length > 0 ? `
                            <div class="card-collections-strip">
                                ${displayCols.map(cn => `<span class="${getCollectionChipClass(cn)}">${escapeHtml(cn)}</span>`).join('')}
                            </div>
                        ` : ''}

                        <div class="card-price-row">
                            ${priceBlock}

                            <button type="button" class="btn-card-action" data-prod-id="${safeId}">
                                <i class="ph-bold ph-chart-line-up"></i> Historial
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    } else {
        container.className = 'table-glass-wrap glass-card';
        container.innerHTML = `
            <table class="glass-table">
                <thead>
                    <tr>
                        <th style="width: 120px;">Foto</th>
                        <th>Producto / Modelo</th>
                        <th>Categoría</th>
                        <th>Estado / Stock</th>
                        <th>Precio Actual</th>
                        <th>Precio Lista / Anterior</th>
                        <th>Variación / Descuento</th>
                        <th>Mínimo Histórico</th>
                        <th>Acción</th>
                    </tr>
                </thead>
                <tbody>
                    ${products.map(p => {
                        const safeId = escapeHtml(String(p.id || ''));
                        const safeImg = escapeHtml(sanitizeUrl(p.imagen_url, false) || FALLBACK_PRODUCT_IMG);
                        const inStock = p.disponible === 1 && Number(p.stock) > 0 && Number(p.precio_actual) > 0;
                        const discountPct = Number(p.descuento_porcentaje) || 0;
                        const hasDiscount = inStock && discountPct > 0 && Number(p.precio_lista) > Number(p.precio_actual);
                        const isMin = inStock && p.es_minimo_historico === 1;

                        const hasPriceChange = p.cambio_reciente === 1 && Number(p.diferencia_precio) !== 0 && Number(p.precio_anterior) > 0;
                        const isPriceDrop = hasPriceChange && Number(p.diferencia_precio) < 0;

                        const isJustExhausted = p.recien_agotado === 1;
                        const isRestocked = p.recien_reabastecido === 1;
                        const stockQty = Math.max(0, Number(p.stock) || 0);
                        const isLowStock = inStock && stockQty > 0 && stockQty <= 3;

                        const teasers = Array.isArray(p.teasers) ? p.teasers : [];
                        const regalos = Array.isArray(p.regalos) ? p.regalos : [];
                        const buyTogether = Array.isArray(p.buy_together) ? p.buy_together : [];
                        const displayCols = getDisplayCollections(p.colecciones).slice(0, 2);

                        return `
                            <tr class="${inStock ? '' : 'is-out-of-stock'}">
                                <td>
                                    <img src="${safeImg}" 
                                         alt="${escapeHtml(p.nombre)}" class="prod-thumb-large" loading="lazy">
                                </td>
                                <td>
                                    <div class="table-prod-title">${escapeHtml(p.nombre)}</div>
                                    <div class="card-sku">SKU: ${escapeHtml(p.sku || p.id)}</div>
                                    ${(teasers.length || regalos.length || buyTogether.length || displayCols.length) ? `
                                        <div class="card-collections-strip" style="margin-top: 6px; margin-bottom: 0;">
                                            ${regalos.length ? `<span class="col-chip col-sale">🎁 Regalo</span>` : ''}
                                            ${teasers.map(t => `<span class="col-chip col-special">🏷️ ${escapeHtml(t.name)}</span>`).join('')}
                                            ${buyTogether.length ? `<span class="col-chip col-special">🤝 Buy Together</span>` : ''}
                                            ${displayCols.map(cn => `<span class="${getCollectionChipClass(cn)}">${escapeHtml(cn)}</span>`).join('')}
                                        </div>
                                    ` : ''}
                                </td>
                                <td><span class="glass-badge badge-accent">${escapeHtml(p.categoria || 'General')}</span></td>
                                <td>
                                    ${isRestocked ? `
                                        <span class="badge-restocked-table">
                                            <i class="ph-bold ph-arrow-counter-clockwise"></i> ¡Volvió a Tener Stock! (${stockQty})
                                        </span>
                                    ` : (isJustExhausted ? `
                                        <span class="badge-just-exhausted-table">
                                            <i class="ph-bold ph-warning"></i> ¡Recién Agotado!
                                        </span>
                                    ` : (inStock ? `
                                        <span class="glass-badge ${isLowStock ? 'badge-amber' : 'badge-emerald'}" style="font-weight:700;">
                                            <i class="ph-bold ${isLowStock ? 'ph-lightning' : 'ph-check'}"></i> ${isLowStock ? `¡Últimas ${stockQty} unid.!` : `${stockQty} unid. en stock`}
                                        </span>
                                    ` : `
                                        <span class="badge-out-of-stock-table">
                                            <i class="ph-bold ph-x-circle"></i> Agotado (0)
                                        </span>
                                    `))}
                                </td>
                                <td>
                                    ${inStock ? `
                                        <div class="price-current-liquid ${isMin ? 'text-emerald' : ''}">${formatBs(p.precio_actual)}</div>
                                        ${hasPriceChange ? `<div class="table-price-prev">Antes: ${formatBs(p.precio_anterior)}</div>` : ''}
                                    ` : (Number(p.precio_actual) > 0 ? `
                                        <div class="price-out-of-stock">${formatBs(p.precio_actual)}</div>
                                    ` : `
                                        <span class="price-unavailable">Sin Stock</span>
                                    `)}
                                </td>
                                <td>
                                    ${hasPriceChange ? `
                                        <span class="table-price-prev">Antes: ${formatBs(p.precio_anterior)}</span>
                                    ` : (inStock && hasDiscount ? `<span class="price-strike-liquid">${formatBs(p.precio_lista)}</span>` : '<span style="color:var(--text-muted);">-</span>')}
                                </td>
                                <td>
                                    ${hasPriceChange ? (isPriceDrop ? `
                                        <span class="glass-badge badge-emerald">🔻 -${formatBs(Math.abs(p.diferencia_precio))}</span>
                                    ` : `
                                        <span class="glass-badge badge-amber">🔺 +${formatBs(p.diferencia_precio)}</span>
                                    `) : (inStock && hasDiscount ? `<span class="glass-badge" style="background:rgba(244,63,94,0.15); color:var(--accent-rose); border-color:rgba(244,63,94,0.3); font-weight:800;">-${escapeHtml(discountPct)}%</span>` : '<span style="color:var(--text-muted);">-</span>')}
                                </td>
                                <td>
                                    ${isMin ? `
                                        <span class="glass-badge badge-emerald">
                                            <i class="ph-bold ph-star"></i> Mínimo
                                        </span>
                                    ` : (inStock && Number(p.min_historico) > 0 ? `
                                        <span style="font-size: 0.82rem; color: var(--text-secondary);">${formatBs(p.min_historico)}</span>
                                    ` : '<span style="color:var(--text-muted);">-</span>')}
                                </td>
                                <td>
                                    <button type="button" class="btn-card-action" data-prod-id="${safeId}">
                                        <i class="ph-bold ph-chart-line-up"></i> Historial
                                    </button>
                                </td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        `;
    }
}

// Cargar y mostrar Campañas Publicitarias Pasadas & Imperdibles
async function loadCampaigns() {
    const grid = document.getElementById('campaigns-grid');
    if (!grid) return;
    grid.innerHTML = '<div style="color: var(--text-secondary); padding: 20px;"><i class="ph-bold ph-spinner spinner"></i> Cargando campañas y banners archivados...</div>';

    try {
        const campaigns = await fetchJsonSafe('/api/campaigns');
        if (!Array.isArray(campaigns)) {
            throw new Error('Respuesta inesperada de campañas');
        }

        const statTotal = document.getElementById('stat-total-campaigns');
        if (statTotal) statTotal.textContent = campaigns.length;

        if (campaigns.length === 0) {
            grid.innerHTML = `
                <div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: var(--text-secondary);">
                    No hay campañas archivadas aún. Haz clic en "Actualizar Sony" para extraer los banners vigentes.
                </div>
            `;
            return;
        }

        grid.innerHTML = campaigns.map(c => {
            const safePortada = escapeHtml(sanitizeUrl(c.banner_portada, true) || FALLBACK_CAMPAIGN_IMG);
            const campId = Number(c.id) || 0;
            const isActive = c.activa === 1;
            const totalBanners = Number(c.total_banners) || 0;

            return `
                <div class="campaign-glass-card" data-camp-id="${campId}">
                    <div class="camp-glass-img-stage">
                        <img src="${safePortada}" alt="${escapeHtml(c.titulo)}" class="camp-glass-img" loading="lazy">
                        <span class="camp-glass-date-pill">
                            <i class="ph-bold ph-calendar"></i> ${escapeHtml(c.rango_fechas || c.pre_header || 'Vigente')}
                        </span>
                    </div>

                    <div class="camp-card-content">
                        <span class="camp-pretitle">${escapeHtml(c.pre_header || 'Promoción')}</span>
                        <h3 class="camp-maintitle">${escapeHtml(c.titulo)}</h3>
                        <p class="camp-desc-text">${escapeHtml(c.descripcion || 'Ver promociones y banners asociados a esta campaña.')}</p>

                        <div class="camp-bottom-row">
                            <span class="camp-count-badge">
                                <i class="ph-bold ph-image"></i> ${totalBanners} banner(s) archivado(s)
                            </span>
                            <span class="glass-badge ${isActive ? 'badge-emerald' : 'badge-amber'}">
                                ${isActive ? '🟢 Activa' : '⚪ Pasada'}
                            </span>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        console.error('Error cargando campañas:', e);
        grid.innerHTML = `<div style="color: var(--accent-rose);">Error al cargar campañas: ${escapeHtml(e.message)}</div>`;
    }
}

// Abrir Modal de Historial de Precios
async function openPriceModal(productId) {
    try {
        const data = await fetchJsonSafe(`/api/products/${encodeURIComponent(productId)}/history`);
        if (!data || !data.producto) return;

        const p = data.producto;
        const history = Array.isArray(data.historial) ? data.historial : [];

        const imgEl = document.getElementById('modal-prod-img');
        imgEl.src = sanitizeUrl(p.imagen_url, false) || FALLBACK_PRODUCT_IMG;
        imgEl.alt = p.nombre || 'Producto Sony';
        document.getElementById('modal-prod-name').textContent = p.nombre || '';
        document.getElementById('modal-prod-category').textContent = p.categoria || 'General';
        document.getElementById('modal-prod-sku').textContent = `SKU: ${p.sku || p.id || ''}`;

        const safeProductUrl = sanitizeUrl(p.url_producto, false) || 'https://store.sony.com.bo/';
        document.getElementById('modal-sony-link').href = safeProductUrl;

        const lastRecord = history.length > 0 ? history[history.length - 1] : null;
        const currentPrice = lastRecord ? Number(lastRecord.precio) || 0 : 0;
        const currentStock = lastRecord && lastRecord.stock !== undefined ? Math.max(0, Number(lastRecord.stock) || 0) : 0;
        const inStock = lastRecord ? (lastRecord.disponible === 1 && currentStock > 0 && currentPrice > 0) : false;

        const validPrices = history.filter(h => h.disponible === 1 && Number(h.stock) > 0 && Number(h.precio) > 0).map(h => Number(h.precio));
        const minPrice = validPrices.length > 0 ? Math.min(...validPrices) : currentPrice;
        const maxPrice = validPrices.length > 0 ? Math.max(...validPrices) : currentPrice;
        const listPrice = lastRecord ? (Number(lastRecord.precio_lista) || currentPrice) : currentPrice;
        const savings = inStock && listPrice > currentPrice ? listPrice - currentPrice : 0;

        document.getElementById('modal-price-current').textContent = currentPrice > 0 ? formatBs(currentPrice) : 'Sin Stock';
        document.getElementById('modal-price-min').textContent = minPrice > 0 ? formatBs(minPrice) : 'No disponible';
        document.getElementById('modal-price-max').textContent = maxPrice > 0 ? formatBs(maxPrice) : 'No disponible';
        document.getElementById('modal-price-savings').textContent = savings > 0 ? formatBs(savings) : 'Sin descuento';

        // Stock actual y estado
        const stockCurEl = document.getElementById('modal-stock-current');
        if (stockCurEl) stockCurEl.textContent = `${currentStock} unid.`;

        const cachedProd = currentProducts.find(item => String(item.id) === String(productId));
        const isRestocked = (p.recien_reabastecido === 1) || (cachedProd && cachedProd.recien_reabastecido === 1);
        const isExhausted = (p.recien_agotado === 1) || (cachedProd && cachedProd.recien_agotado === 1);

        const stockStatusEl = document.getElementById('modal-stock-status');
        if (stockStatusEl) {
            if (inStock && isRestocked) {
                stockStatusEl.textContent = `🎉 ¡Volvió a tener stock! (${currentStock} unid.)`;
                stockStatusEl.className = 'subcard-val text-emerald';
            } else if (inStock) {
                if (currentStock <= 3) {
                    stockStatusEl.textContent = `⚡ ¡Últimas ${currentStock} unid.!`;
                    stockStatusEl.className = 'subcard-val text-amber';
                } else {
                    stockStatusEl.textContent = `🟢 En Inventario`;
                    stockStatusEl.className = 'subcard-val text-emerald';
                }
            } else {
                if (isExhausted) {
                    stockStatusEl.textContent = `⚠️ ¡Recién Agotado!`;
                    stockStatusEl.className = 'subcard-val text-amber';
                } else {
                    stockStatusEl.textContent = `🔴 Agotado / Sin Stock`;
                    stockStatusEl.className = 'subcard-val text-rose';
                }
            }
        }

        renderModalPromosAndCollections(p);
        renderChart(history, minPrice);
        renderStockChart(history, currentStock);

        document.getElementById('price-modal').classList.add('open');
    } catch (e) {
        console.error('Error abriendo modal de precio:', e);
        showToast(`No se pudo cargar el historial: ${e.message}`);
    }
}

function renderModalPromosAndCollections(p) {
    const panel = document.getElementById('modal-promos-section');
    const promosList = document.getElementById('modal-promos-list');
    const colsRow = document.getElementById('modal-collections-row');
    if (!panel || !promosList || !colsRow) return;

    const teasers = Array.isArray(p.teasers) ? p.teasers : [];
    const regalos = Array.isArray(p.regalos) ? p.regalos : [];
    const buyTogether = Array.isArray(p.buy_together) ? p.buy_together : [];
    const cols = getDisplayCollections(p.colecciones);

    const promoPills = [];

    regalos.forEach(g => {
        const gUrl = sanitizeUrl(g.url_producto, false);
        const gLabel = escapeHtml(g.nombre || `SKU ${g.sku}`);
        promoPills.push(`
            <div class="promo-pill-card promo-gift">
                <i class="ph-bold ph-gift"></i>
                <span><b>Regalo incluido:</b> ${gUrl ? `<a href="${escapeHtml(gUrl)}" target="_blank" rel="noopener noreferrer">${gLabel}</a>` : gLabel}</span>
            </div>
        `);
    });

    teasers.forEach(t => {
        const minQty = Number(t.min_qty) || 1;
        const qtyNote = minQty > 1 ? ` (llevando ${minQty}+ unidades)` : '';
        promoPills.push(`
            <div class="promo-pill-card">
                <i class="ph-bold ph-tag"></i>
                <span><b>Promo activa:</b> ${escapeHtml(t.name)}${escapeHtml(qtyNote)}</span>
            </div>
        `);
    });

    buyTogether.forEach(bt => {
        const btUrl = sanitizeUrl(bt.url_producto, false);
        const btLabel = escapeHtml(bt.nombre || `SKU ${bt.sku}`);
        promoPills.push(`
            <div class="promo-pill-card promo-buytogether">
                <i class="ph-bold ph-handshake"></i>
                <span><b>Combínalo con (Buy Together):</b> ${btUrl ? `<a href="${escapeHtml(btUrl)}" target="_blank" rel="noopener noreferrer">${btLabel}</a>` : btLabel}</span>
            </div>
        `);
    });

    if (promoPills.length === 0 && cols.length === 0) {
        panel.classList.add('is-hidden');
        promosList.innerHTML = '';
        colsRow.innerHTML = '';
        return;
    }

    promosList.innerHTML = promoPills.join('');
    promosList.classList.toggle('is-hidden', promoPills.length === 0);

    if (cols.length > 0) {
        colsRow.innerHTML = `<span class="collections-row-label"><i class="ph-bold ph-bookmarks"></i> Colecciones:</span>` +
            cols.map(cn => `<span class="${getCollectionChipClass(cn)}">${escapeHtml(cn)}</span>`).join('');
        colsRow.classList.remove('is-hidden');
    } else {
        colsRow.innerHTML = '';
        colsRow.classList.add('is-hidden');
    }

    panel.classList.remove('is-hidden');
}

// Renderizar Gráfica de Precios Escalonada
function renderChart(history, minPrice) {
    const ctx = document.getElementById('priceHistoryChart').getContext('2d');
    if (priceChart) {
        priceChart.destroy();
    }

    let labels = [];
    let fullTimestamps = [];
    let priceData = [];
    let minData = [];

    const activeHistory = history.filter(h => Number(h.precio) > 0);

    if (activeHistory.length === 0) {
        labels = ['Sin registros con precio'];
        fullTimestamps = ['Sin registros'];
        priceData = [0];
        minData = [0];
    } else if (activeHistory.length === 1) {
        const ts = activeHistory[0].fecha_registro || '';
        labels = ['Registro Inicial', formatShortTimestamp(ts)];
        fullTimestamps = ['Registro Inicial', ts];
        priceData = [Number(activeHistory[0].precio), Number(activeHistory[0].precio)];
        minData = [minPrice, minPrice];
    } else {
        labels = activeHistory.map(h => formatShortTimestamp(h.fecha_registro));
        fullTimestamps = activeHistory.map(h => h.fecha_registro || '');
        priceData = activeHistory.map(h => Number(h.precio));
        minData = activeHistory.map(() => minPrice);
    }

    const gradient = ctx.createLinearGradient(0, 0, 0, 260);
    gradient.addColorStop(0, 'rgba(16, 185, 129, 0.35)');
    gradient.addColorStop(1, 'rgba(16, 185, 129, 0.0)');

    priceChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Precio Registrado (Bs.)',
                    data: priceData,
                    borderColor: '#10b981',
                    backgroundColor: gradient,
                    borderWidth: 3,
                    stepped: 'before',
                    fill: true,
                    pointBackgroundColor: '#10b981',
                    pointBorderColor: '#ffffff',
                    pointBorderWidth: 1.5,
                    pointRadius: 4,
                    pointHoverRadius: 7
                },
                {
                    label: 'Mínimo Histórico (All-Time Low)',
                    data: minData,
                    borderColor: '#38bdf8',
                    borderDash: [6, 6],
                    borderWidth: 2,
                    fill: false,
                    pointRadius: 0,
                    pointHoverRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: {
                        color: '#cbd5e1',
                        font: { family: 'Plus Jakarta Sans', size: 12, weight: 600 }
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(18, 24, 38, 0.95)',
                    titleColor: '#f8fafc',
                    bodyColor: '#34d399',
                    borderColor: 'rgba(255, 255, 255, 0.15)',
                    borderWidth: 1,
                    padding: 12,
                    cornerRadius: 12,
                    callbacks: {
                        title: function(items) {
                            const idx = items && items[0] ? items[0].dataIndex : 0;
                            return fullTimestamps[idx] || '';
                        },
                        label: function(context) {
                            return `${context.dataset.label}: ${formatBs(context.parsed.y)}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.06)' },
                    ticks: { color: '#94a3b8', font: { family: 'Plus Jakarta Sans' } }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.06)' },
                    ticks: {
                        color: '#94a3b8',
                        font: { family: 'Plus Jakarta Sans' },
                        callback: function(value) {
                            return `Bs. ${value.toLocaleString()}`;
                        }
                    }
                }
            }
        }
    });
}

// Renderizar Gráfica de Evolución de Stock Disponible en el Tiempo
function renderStockChart(history, currentStock) {
    const canvas = document.getElementById('stockHistoryChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (stockChart) {
        stockChart.destroy();
    }

    let labels = [];
    let fullTimestamps = [];
    let stockData = [];

    if (!history || history.length === 0) {
        labels = ['Hoy'];
        fullTimestamps = ['Hoy'];
        stockData = [currentStock];
    } else if (history.length === 1) {
        const ts = history[0].fecha_registro || '';
        const qty = history[0].stock !== undefined ? Number(history[0].stock) : 0;
        labels = ['Registro Inicial', formatShortTimestamp(ts)];
        fullTimestamps = ['Registro Inicial', ts];
        stockData = [qty, qty];
    } else {
        labels = history.map(h => formatShortTimestamp(h.fecha_registro));
        fullTimestamps = history.map(h => h.fecha_registro || '');
        stockData = history.map(h => (h.stock !== undefined ? Number(h.stock) : 0));
    }

    const gradient = ctx.createLinearGradient(0, 0, 0, 240);
    gradient.addColorStop(0, 'rgba(168, 85, 247, 0.35)');
    gradient.addColorStop(1, 'rgba(168, 85, 247, 0.0)');

    stockChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Unidades Disponibles en Inventario',
                    data: stockData,
                    borderColor: '#a855f7',
                    backgroundColor: gradient,
                    borderWidth: 3,
                    stepped: 'before',
                    fill: true,
                    pointBackgroundColor: '#a855f7',
                    pointBorderColor: '#ffffff',
                    pointBorderWidth: 1.5,
                    pointRadius: 4,
                    pointHoverRadius: 7
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: {
                        color: '#cbd5e1',
                        font: { family: 'Plus Jakarta Sans', size: 12, weight: 600 }
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(18, 24, 38, 0.95)',
                    titleColor: '#f8fafc',
                    bodyColor: '#c084fc',
                    borderColor: 'rgba(255, 255, 255, 0.15)',
                    borderWidth: 1,
                    padding: 12,
                    cornerRadius: 12,
                    callbacks: {
                        title: function(items) {
                            const idx = items && items[0] ? items[0].dataIndex : 0;
                            return fullTimestamps[idx] || '';
                        },
                        label: function(context) {
                            return `${context.dataset.label}: ${context.parsed.y} unid.`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.06)' },
                    ticks: { color: '#94a3b8', font: { family: 'Plus Jakarta Sans' } }
                },
                y: {
                    beginAtZero: true,
                    grid: { color: 'rgba(255, 255, 255, 0.06)' },
                    ticks: {
                        color: '#94a3b8',
                        stepSize: 1,
                        precision: 0,
                        font: { family: 'Plus Jakarta Sans' },
                        callback: function(value) {
                            return `${value} unid.`;
                        }
                    }
                }
            }
        }
    });
}

function closePriceModal() {
    const modal = document.getElementById('price-modal');
    if (modal) modal.classList.remove('open');
}

// Abrir Modal de Campaña
async function openCampaignModal(campId) {
    try {
        const camp = await fetchJsonSafe(`/api/campaigns/${encodeURIComponent(campId)}`);
        if (!camp) return;

        document.getElementById('modal-camp-title').textContent = camp.titulo || '';
        document.getElementById('modal-camp-dates').textContent = `📅 ${camp.rango_fechas || camp.pre_header || 'Vigente'}`;
        document.getElementById('modal-camp-status').textContent = camp.activa === 1 ? '🟢 Promoción Activa' : '⚪ Promoción Pasada';
        document.getElementById('modal-camp-desc').textContent = camp.descripcion || camp.pre_header || '';

        const bannersList = document.getElementById('modal-banners-list');
        const banners = Array.isArray(camp.banners) ? camp.banners : [];

        if (banners.length === 0) {
            bannersList.innerHTML = '<p style="color:var(--text-secondary);">No se encontraron banners guardados para esta campaña.</p>';
        } else {
            const tipoMap = {
                'desktop': '🖥️ Desktop',
                'mobile': '📱 Móvil',
                'imperdibles': '⭐ Imperdible',
                'cintillo': '🏷️ Cintillo',
                'favoritos': '❤️ Favoritos',
                'popup': '🎯 Popup'
            };
            bannersList.innerHTML = banners.map((b, idx) => {
                const safeImgSrc = escapeHtml(
                    sanitizeUrl(b.archivo_local, true) || sanitizeUrl(b.url_remota, false) || FALLBACK_CAMPAIGN_IMG
                );
                const safeRedirect = sanitizeUrl(b.enlace_redireccion, false);
                const tipoLabel = tipoMap[String(b.tipo || 'desktop').toLowerCase()] || escapeHtml(b.tipo || '');
                return `
                    <div class="banner-glass-wrapper">
                        <img src="${safeImgSrc}" alt="Banner ${idx + 1}" class="banner-full-img" loading="lazy">
                        <div class="banner-glass-foot">
                            <span><i class="ph-bold ph-calendar-check"></i> ${escapeHtml(tipoLabel)} • Archivado el: ${escapeHtml(b.fecha_captura || '')}</span>
                            ${safeRedirect ? `
                                <a href="${escapeHtml(safeRedirect)}" target="_blank" rel="noopener noreferrer">
                                    Abrir Promoción en Sony <i class="ph-bold ph-arrow-square-out"></i>
                                </a>
                            ` : ''}
                        </div>
                    </div>
                `;
            }).join('');
        }

        document.getElementById('campaign-modal').classList.add('open');
    } catch (e) {
        console.error('Error abriendo modal de campaña:', e);
        showToast(`Error abriendo campaña: ${e.message}`);
    }
}

function closeCampaignModal() {
    const modal = document.getElementById('campaign-modal');
    if (modal) modal.classList.remove('open');
}

// Sincronización manual inteligente con protección CSRF y sondeo en tiempo real
async function triggerSync() {
    const syncBtn = document.getElementById('sync-btn');
    const icon = document.getElementById('sync-icon');
    if (icon) icon.classList.add('spinner');
    if (syncBtn) syncBtn.disabled = true;
    showToast('Iniciando sincronización con Sony Store Bolivia...');

    try {
        const postData = await fetchJsonSafe('/api/sync', {
            method: 'POST',
            headers: {
                'X-Requested-With': 'SonyTrackerUI'
            }
        });

        if (postData.status === 'ya_en_progreso') {
            showToast('Ya hay una sincronización activa. Esperando resultados...');
        } else {
            showToast('Analizando productos, precios y variaciones de stock...');
        }

        if (syncPollInterval) clearInterval(syncPollInterval);

        syncPollInterval = setInterval(async () => {
            try {
                const syncStatus = await fetchJsonSafe('/api/sync/status');

                if (!syncStatus.is_syncing && syncStatus.estado === 'completado') {
                    clearInterval(syncPollInterval);
                    syncPollInterval = null;
                    if (icon) icon.classList.remove('spinner');
                    if (syncBtn) syncBtn.disabled = false;

                    const cambios = Number(syncStatus.cambios_detectados) || 0;
                    const agotados = Number(syncStatus.agotados_detectados) || 0;
                    const reabastecidos = Number(syncStatus.reabastecidos_detectados) || 0;

                    const msgs = [];
                    if (reabastecidos > 0) msgs.push(`🎉 ${reabastecidos} producto(s) volvieron a tener stock`);
                    if (cambios > 0) msgs.push(`🔔 ${cambios} con cambio de precio`);
                    if (agotados > 0) msgs.push(`⚠️ ${agotados} agotado(s)`);

                    if (msgs.length > 0) {
                        showToast(`¡Actualización finalizada! Se detectaron: ${msgs.join(' y ')}.`, 9000);
                        const sortSelect = document.getElementById('sort-select');
                        const stockSelect = document.getElementById('stock-select');
                        const onlyMinCheckbox = document.getElementById('only-min-checkbox');
                        if (sortSelect && stockSelect) {
                            if (reabastecidos > 0) {
                                sortSelect.value = 'restocked';
                                stockSelect.value = 'restocked';
                            } else if (cambios > 0) {
                                sortSelect.value = 'price_changed';
                                stockSelect.value = 'in_stock';
                            } else if (agotados > 0) {
                                sortSelect.value = 'just_exhausted';
                                stockSelect.value = 'just_exhausted';
                                if (onlyMinCheckbox) onlyMinCheckbox.checked = false;
                            }
                        }
                    } else {
                        showToast('✅ Actualización finalizada: Precios y stock sin cambios.', 5000);
                    }

                    loadCollections();
                    applyFilters();
                    updateGlobalStats();
                    loadCampaigns();
                } else if (!syncStatus.is_syncing && (syncStatus.estado === 'error' || syncStatus.estado === 'interrumpido')) {
                    clearInterval(syncPollInterval);
                    syncPollInterval = null;
                    if (icon) icon.classList.remove('spinner');
                    if (syncBtn) syncBtn.disabled = false;
                    showToast('⚠️ Error durante la sincronización.');
                }
            } catch (err) {
                console.error('Error sondeando sincronización:', err);
            }
        }, 2000);

    } catch (e) {
        console.error(e);
        if (icon) icon.classList.remove('spinner');
        if (syncBtn) syncBtn.disabled = false;
        showToast(`Error al sincronizar: ${e.message}`);
    }
}

function showToast(msg, duration = 4500) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = String(msg || '');
    toast.classList.add('show');
    clearTimeout(toast.timeoutId);
    toast.timeoutId = setTimeout(() => {
        toast.classList.remove('show');
    }, duration);
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/[&<>"']/g, function(m) {
        return {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        }[m];
    });
}
