let priceChart = null;
let stockChart = null;
let currentProducts = [];
let debounceTimer = null;
let viewMode = localStorage.getItem('sony_view_mode') || 'grid';

document.addEventListener('DOMContentLoaded', () => {
    updateViewSwitchButtons();
    loadCategories();
    loadProducts();
    updateGlobalStats();
    loadCampaigns();
});

// Cambiar de modo de vista (Cuadrícula con Fotos Grandes vs Lista)
function setViewMode(mode) {
    viewMode = mode;
    localStorage.setItem('sony_view_mode', mode);
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

    // Desactivar todos
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

// Cargar categorías en el selector de filtros
async function loadCategories() {
    try {
        const res = await fetch('/api/categories');
        const categories = await res.json();
        const select = document.getElementById('category-select');
        if (!select) return;
        select.innerHTML = '<option value="Todas">Todas las Categorías</option>';
        categories.forEach(cat => {
            const opt = document.createElement('option');
            opt.value = cat;
            opt.textContent = cat;
            select.appendChild(opt);
        });
    } catch (e) {
        console.error('Error cargando categorías:', e);
    }
}

// Aplicar filtros con debounce
function applyFiltersDebounced() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
        applyFilters();
    }, 300);
}

async function applyFilters() {
    const q = document.getElementById('search-input') ? document.getElementById('search-input').value.trim() : '';
    const cat = document.getElementById('category-select') ? document.getElementById('category-select').value : 'Todas';
    const onlyMin = document.getElementById('only-min-checkbox') ? document.getElementById('only-min-checkbox').checked : false;
    const sort = document.getElementById('sort-select') ? document.getElementById('sort-select').value : 'discount_desc';
    const stock = document.getElementById('stock-select') ? document.getElementById('stock-select').value : 'in_stock';

    const params = new URLSearchParams({
        q: q,
        category: cat,
        only_min: onlyMin,
        sort: sort,
        stock: stock
    });

    loadProducts(params.toString());
}

// Actualizar barra de métricas globales
async function updateGlobalStats() {
    try {
        const res = await fetch('/api/products?stock=all');
        const allProds = await res.json();
        
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

    container.innerHTML = `
        <div style="text-align: center; padding: 60px; color: var(--text-secondary);">
            <i class="ph-bold ph-spinner spinner" style="font-size: 32px; color: var(--accent-cyan); display:block; margin-bottom: 12px;"></i>
            Cargando catálogo con Liquid Glass UI...
        </div>
    `;

    try {
        const res = await fetch(`/api/products?${queryString}`);
        const products = await res.json();
        currentProducts = products;

        renderProducts(products);
    } catch (e) {
        console.error('Error cargando productos:', e);
        container.innerHTML = `
            <div style="text-align: center; color: var(--accent-rose); padding: 40px;">
                Error al conectar con la base de datos local.
            </div>
        `;
    }
}

// Renderizar productos según la vista seleccionada (Fotos Grandes vs Tabla)
function renderProducts(products) {
    const container = document.getElementById('products-container');
    if (!container) return;

    const sortSelect = document.getElementById('sort-select');
    const isPriceChangedFilter = sortSelect && sortSelect.value === 'price_changed';
    const isJustExhaustedFilter = sortSelect && sortSelect.value === 'just_exhausted';

    if (!products || products.length === 0) {
        let emptyMsg = 'No se encontraron productos con los filtros seleccionados.';
        let emptyIcon = 'ph-ghost';
        if (isPriceChangedFilter) {
            emptyMsg = 'No se encontraron artículos con cambios de precio recientes.';
            emptyIcon = 'ph-bell-slash';
        } else if (isJustExhaustedFilter) {
            emptyMsg = 'No se encontraron artículos que se hayan agotado recientemente.';
            emptyIcon = 'ph-package';
        }

        container.innerHTML = `
            <div style="text-align: center; padding: 60px; color: var(--text-secondary); width: 100%;">
                <i class="ph-bold ${emptyIcon}" style="font-size: 40px; display: block; margin-bottom: 12px; color: var(--accent-cyan);"></i>
                ${emptyMsg}
            </div>
        `;
        return;
    }

    if (viewMode === 'grid') {
        container.className = 'products-cards-grid';
        container.innerHTML = products.map(p => {
            const inStock = p.disponible === 1 && p.stock > 0 && p.precio_actual > 0;
            const hasDiscount = inStock && p.descuento_porcentaje > 0 && p.precio_lista > p.precio_actual;
            const isMin = inStock && p.es_minimo_historico === 1;

            const hasPriceChange = p.diferencia_precio !== 0 && p.precio_anterior > 0;
            const isPriceDrop = hasPriceChange && p.diferencia_precio < 0;
            const isPriceRise = hasPriceChange && p.diferencia_precio > 0;

            const isJustExhausted = p.recien_agotado === 1;
            const isLowStock = inStock && p.stock > 0 && p.stock <= 3;

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
                if (p.precio_actual > 0) {
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
                    <div class="card-img-stage" onclick="openPriceModal('${p.id}')" style="cursor: pointer;">
                        <img src="${p.imagen_url || 'https://via.placeholder.com/260?text=Sony'}" 
                             alt="${escapeHtml(p.nombre)}" 
                             class="card-hero-img" 
                             loading="lazy"
                             onerror="this.src='https://via.placeholder.com/260?text=Sony'">

                        ${inStock && hasDiscount ? `
                            <span class="badge-discount-float">-${p.descuento_porcentaje}%</span>
                        ` : ''}

                        ${isMin ? `
                            <span class="badge-min-low-float" title="Precio actual es el más bajo registrado en Sony Bolivia">
                                <i class="ph-bold ph-star"></i> Mínimo Histórico
                            </span>
                        ` : ''}

                        ${isJustExhausted ? `
                            <span class="badge-just-exhausted-float" title="Se acaba de agotar en la tienda Sony">
                                <i class="ph-bold ph-warning"></i> ¡Recién Agotado!
                            </span>
                        ` : (!inStock ? `
                            <span class="badge-stock-out-float">
                                <i class="ph-bold ph-x-circle"></i> Agotado
                            </span>
                        ` : '')}

                        ${isLowStock ? `
                            <span class="badge-stock-low-float" title="Quedan muy pocas unidades en inventario">
                                <i class="ph-bold ph-lightning"></i> ¡Últimas ${p.stock} unid.!
                            </span>
                        ` : ''}

                        ${isPriceDrop ? `
                            <span class="badge-price-drop-float" title="Precio rebajado recientemente">
                                <i class="ph-bold ph-trend-down"></i> Bajó ${formatBs(Math.abs(p.diferencia_precio))} (${p.porcentaje_cambio_precio}%)
                            </span>
                        ` : ''}

                        ${isPriceRise ? `
                            <span class="badge-price-rise-float" title="Precio aumentado recientemente">
                                <i class="ph-bold ph-trend-up"></i> Subió ${formatBs(p.diferencia_precio)} (+${p.porcentaje_cambio_precio}%)
                            </span>
                        ` : ''}
                    </div>

                    <div class="card-details">
                        <div class="card-cat-row">
                            <span class="glass-badge badge-accent">${escapeHtml(p.categoria || 'General')}</span>
                            ${inStock ? `
                                <span class="badge-stock-pill ${isLowStock ? 'stock-low' : 'stock-plenty'}">
                                    <i class="ph-bold ${isLowStock ? 'ph-lightning' : 'ph-package'}"></i> Stock: ${p.stock} unid.
                                </span>
                            ` : `
                                <span class="badge-stock-pill stock-zero">
                                    <i class="ph-bold ph-x-circle"></i> Stock: 0
                                </span>
                            `}
                        </div>

                        <h3 class="card-title" title="${escapeHtml(p.nombre)}" onclick="openPriceModal('${p.id}')" style="cursor: pointer;">
                            ${escapeHtml(p.nombre)}
                        </h3>

                        <div class="card-price-row">
                            ${priceBlock}

                            <button class="btn-card-action" onclick="openPriceModal('${p.id}')">
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
                        const inStock = p.disponible === 1 && p.stock > 0 && p.precio_actual > 0;
                        const hasDiscount = inStock && p.descuento_porcentaje > 0 && p.precio_lista > p.precio_actual;
                        const isMin = inStock && p.es_minimo_historico === 1;

                        const hasPriceChange = p.diferencia_precio !== 0 && p.precio_anterior > 0;
                        const isPriceDrop = hasPriceChange && p.diferencia_precio < 0;
                        const isPriceRise = hasPriceChange && p.diferencia_precio > 0;

                        const isJustExhausted = p.recien_agotado === 1;
                        const isLowStock = inStock && p.stock > 0 && p.stock <= 3;

                        return `
                            <tr class="${inStock ? '' : 'is-out-of-stock'}">
                                <td>
                                    <img src="${p.imagen_url || 'https://via.placeholder.com/100?text=Sony'}" 
                                         alt="${escapeHtml(p.nombre)}" class="prod-thumb-large" loading="lazy"
                                         onerror="this.src='https://via.placeholder.com/100?text=Sony'">
                                </td>
                                <td>
                                    <div class="table-prod-title">${escapeHtml(p.nombre)}</div>
                                    <div class="card-sku">SKU: ${p.sku || p.id}</div>
                                </td>
                                <td><span class="glass-badge badge-accent">${escapeHtml(p.categoria || 'General')}</span></td>
                                <td>
                                    ${isJustExhausted ? `
                                        <span class="badge-just-exhausted-table">
                                            <i class="ph-bold ph-warning"></i> ¡Recién Agotado!
                                        </span>
                                    ` : (inStock ? `
                                        <span class="glass-badge ${isLowStock ? 'badge-amber' : 'badge-emerald'}" style="font-weight:700;">
                                            <i class="ph-bold ${isLowStock ? 'ph-lightning' : 'ph-check'}"></i> ${isLowStock ? '¡Últimas ' + p.stock + ' unid.!' : p.stock + ' unid. en stock'}
                                        </span>
                                    ` : `
                                        <span class="badge-out-of-stock-table">
                                            <i class="ph-bold ph-x-circle"></i> Agotado (0)
                                        </span>
                                    `)}
                                </td>
                                <td>
                                    ${inStock ? `
                                        <div class="price-current-liquid ${isMin ? 'text-emerald' : ''}">${formatBs(p.precio_actual)}</div>
                                        ${hasPriceChange ? `<div class="table-price-prev">Antes: ${formatBs(p.precio_anterior)}</div>` : ''}
                                    ` : (p.precio_actual > 0 ? `
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
                                    `) : (inStock && hasDiscount ? `<span class="glass-badge" style="background:rgba(244,63,94,0.15); color:var(--accent-rose); border-color:rgba(244,63,94,0.3); font-weight:800;">-${p.descuento_porcentaje}%</span>` : '<span style="color:var(--text-muted);">-</span>')}
                                </td>
                                <td>
                                    ${isMin ? `
                                        <span class="glass-badge badge-emerald">
                                            <i class="ph-bold ph-star"></i> Mínimo
                                        </span>
                                    ` : (inStock ? `
                                        <span style="font-size: 0.82rem; color: var(--text-secondary);">${formatBs(p.min_historico)}</span>
                                    ` : '<span style="color:var(--text-muted);">-</span>')}
                                </td>
                                <td>
                                    <button class="btn-card-action" onclick="openPriceModal('${p.id}')">
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
        const res = await fetch('/api/campaigns');
        const campaigns = await res.json();

        const statTotal = document.getElementById('stat-total-campaigns');
        if (statTotal) statTotal.textContent = campaigns.length;

        if (!campaigns || campaigns.length === 0) {
            grid.innerHTML = `
                <div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: var(--text-secondary);">
                    No hay campañas archivadas aún. Haz clic en "Actualizar Sony" para extraer los banners vigentes.
                </div>
            `;
            return;
        }

        grid.innerHTML = campaigns.map(c => {
            const portada = c.banner_portada || 'https://via.placeholder.com/400x200?text=Campaña+Sony';
            const isActive = c.activa === 1;

            return `
                <div class="campaign-glass-card" onclick="openCampaignModal(${c.id})">
                    <div class="camp-glass-img-stage">
                        <img src="${portada}" alt="${escapeHtml(c.titulo)}" class="camp-glass-img" loading="lazy">
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
                                <i class="ph-bold ph-image"></i> ${c.total_banners} banner(s) archivado(s)
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
        grid.innerHTML = '<div style="color: var(--accent-rose);">Error al cargar campañas.</div>';
    }
}

// Abrir Modal de Historial de Precios
async function openPriceModal(productId) {
    try {
        const res = await fetch(`/api/products/${productId}/history`);
        const data = await res.json();
        if (!data || !data.producto) return;

        const p = data.producto;
        const history = data.historial || [];

        document.getElementById('modal-prod-img').src = p.imagen_url || '';
        document.getElementById('modal-prod-name').textContent = p.nombre;
        document.getElementById('modal-prod-category').textContent = p.categoria || 'General';
        document.getElementById('modal-prod-sku').textContent = `SKU: ${p.sku || p.id}`;
        document.getElementById('modal-sony-link').href = p.url_producto || `https://store.sony.com.bo/`;

        const lastRecord = history.length > 0 ? history[history.length - 1] : null;
        const currentPrice = lastRecord ? lastRecord.precio : 0;
        const currentStock = lastRecord ? (lastRecord.stock !== undefined ? lastRecord.stock : 0) : 0;
        const inStock = lastRecord ? (lastRecord.disponible === 1 && currentStock > 0 && currentPrice > 0) : false;

        const validPrices = history.filter(h => h.disponible === 1 && h.stock > 0 && h.precio > 0).map(h => h.precio);
        const minPrice = validPrices.length > 0 ? Math.min(...validPrices) : currentPrice;
        const maxPrice = validPrices.length > 0 ? Math.max(...validPrices) : currentPrice;
        const listPrice = lastRecord ? (lastRecord.precio_lista || currentPrice) : currentPrice;
        const savings = inStock && listPrice > currentPrice ? listPrice - currentPrice : 0;

        document.getElementById('modal-price-current').textContent = currentPrice > 0 ? formatBs(currentPrice) : 'Sin Stock';
        document.getElementById('modal-price-min').textContent = minPrice > 0 ? formatBs(minPrice) : 'No disponible';
        document.getElementById('modal-price-max').textContent = maxPrice > 0 ? formatBs(maxPrice) : 'No disponible';
        document.getElementById('modal-price-savings').textContent = savings > 0 ? formatBs(savings) : 'Sin descuento';

        // Stock actual y estado
        const stockCurEl = document.getElementById('modal-stock-current');
        if (stockCurEl) stockCurEl.textContent = `${currentStock} unid.`;

        const stockStatusEl = document.getElementById('modal-stock-status');
        if (stockStatusEl) {
            if (inStock) {
                if (currentStock <= 3) {
                    stockStatusEl.textContent = `⚡ ¡Últimas ${currentStock} unid.!`;
                    stockStatusEl.className = 'subcard-val text-amber';
                } else {
                    stockStatusEl.textContent = `🟢 En Inventario`;
                    stockStatusEl.className = 'subcard-val text-emerald';
                }
            } else {
                stockStatusEl.textContent = `🔴 Agotado / Sin Stock`;
                stockStatusEl.className = 'subcard-val text-rose';
            }
        }

        renderChart(history, minPrice);
        renderStockChart(history, currentStock);

        document.getElementById('price-modal').classList.add('open');
    } catch (e) {
        console.error('Error abriendo modal de precio:', e);
    }
}

// Renderizar Gráfica de Precios estilo SteamDB
function renderChart(history, minPrice) {
    const ctx = document.getElementById('priceHistoryChart').getContext('2d');
    if (priceChart) {
        priceChart.destroy();
    }

    let labels = [];
    let priceData = [];
    let minData = [];

    const activeHistory = history.filter(h => h.precio > 0);

    if (activeHistory.length === 0) {
        labels = ['Sin registros con precio'];
        priceData = [0];
        minData = [0];
    } else if (activeHistory.length === 1) {
        const dateStr = activeHistory[0].fecha_registro.split(' ')[0];
        labels = [`Registro Inicial`, dateStr];
        priceData = [activeHistory[0].precio, activeHistory[0].precio];
        minData = [minPrice, minPrice];
    } else {
        labels = activeHistory.map(h => h.fecha_registro.split(' ')[0]);
        priceData = activeHistory.map(h => h.precio);
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
    let stockData = [];

    if (!history || history.length === 0) {
        labels = ['Hoy'];
        stockData = [currentStock];
    } else if (history.length === 1) {
        const dateStr = history[0].fecha_registro.split(' ')[0];
        labels = ['Registro Inicial', dateStr];
        stockData = [history[0].stock || 0, history[0].stock || 0];
    } else {
        labels = history.map(h => (h.fecha_registro ? h.fecha_registro.split(' ')[0] : ''));
        stockData = history.map(h => (h.stock !== undefined ? h.stock : 0));
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

function closeModalOnBackdrop(event) {
    if (event.target.id === 'price-modal') {
        closePriceModal();
    }
}

// Abrir Modal de Campaña
async function openCampaignModal(campId) {
    try {
        const res = await fetch(`/api/campaigns/${campId}`);
        const camp = await res.json();
        if (!camp) return;

        document.getElementById('modal-camp-title').textContent = camp.titulo;
        document.getElementById('modal-camp-dates').textContent = `📅 ${camp.rango_fechas || camp.pre_header || 'Vigente'}`;
        document.getElementById('modal-camp-status').textContent = camp.activa === 1 ? '🟢 Promoción Activa' : '⚪ Promoción Pasada';
        document.getElementById('modal-camp-desc').textContent = camp.descripcion || camp.pre_header || '';

        const bannersList = document.getElementById('modal-banners-list');
        const banners = camp.banners || [];

        if (banners.length === 0) {
            bannersList.innerHTML = '<p style="color:var(--text-secondary);">No se encontraron banners guardados para esta campaña.</p>';
        } else {
            bannersList.innerHTML = banners.map((b, idx) => `
                <div class="banner-glass-wrapper">
                    <img src="${b.archivo_local || b.url_remota}" alt="Banner ${idx + 1}" class="banner-full-img" loading="lazy">
                    <div class="banner-glass-foot">
                        <span><i class="ph-bold ph-calendar-check"></i> Archivado el: ${b.fecha_captura}</span>
                        ${b.enlace_redireccion ? `
                            <a href="${b.enlace_redireccion}" target="_blank" rel="noopener noreferrer">
                                Abrir Promoción en Sony <i class="ph-bold ph-arrow-square-out"></i>
                            </a>
                        ` : ''}
                    </div>
                </div>
            `).join('');
        }

        document.getElementById('campaign-modal').classList.add('open');
    } catch (e) {
        console.error('Error abriendo modal de campaña:', e);
    }
}

function closeCampaignModal() {
    const modal = document.getElementById('campaign-modal');
    if (modal) modal.classList.remove('open');
}

function closeCampaignModalOnBackdrop(event) {
    if (event.target.id === 'campaign-modal') {
        closeCampaignModal();
    }
}

// Sincronización manual inteligente con sondeo en tiempo real
let syncPollInterval = null;

async function triggerSync() {
    const icon = document.getElementById('sync-icon');
    if (icon) icon.classList.add('spinner');
    showToast('Iniciando sincronización con Sony Store Bolivia...');

    try {
        const postRes = await fetch('/api/sync', { method: 'POST' });
        const postData = await postRes.json();
        
        if (postData.status === 'ya_en_progreso') {
            showToast('Ya hay una sincronización activa. Esperando resultados...');
        } else {
            showToast('Analizando productos y comprobando cambios de precio...');
        }

        if (syncPollInterval) clearInterval(syncPollInterval);

        syncPollInterval = setInterval(async () => {
            try {
                const statusRes = await fetch('/api/sync/status');
                const syncStatus = await statusRes.json();

                if (!syncStatus.is_syncing && syncStatus.estado === 'completado') {
                    clearInterval(syncPollInterval);
                    syncPollInterval = null;
                    if (icon) icon.classList.remove('spinner');

                    const cambios = syncStatus.cambios_detectados || 0;
                    const agotados = syncStatus.agotados_detectados || 0;

                    if (cambios > 0 && agotados > 0) {
                        showToast(`🔔 ¡Actualización finalizada! Se detectaron <b>${cambios}</b> artículo(s) con cambio de precio y <b>${agotados}</b> producto(s) que se agotaron.`, 9000);
                        const sortSelect = document.getElementById('sort-select');
                        if (sortSelect) sortSelect.value = 'price_changed';
                    } else if (agotados > 0) {
                        showToast(`⚠️ ¡Actualización finalizada! <b>${agotados}</b> producto(s) se acaban de agotar en tienda.`, 8000);
                        const sortSelect = document.getElementById('sort-select');
                        if (sortSelect) sortSelect.value = 'just_exhausted';
                    } else if (cambios > 0) {
                        showToast(`🔔 ¡Actualización finalizada! Se detectaron <b>${cambios}</b> artículo(s) con cambio de precio.`, 8000);
                        const sortSelect = document.getElementById('sort-select');
                        if (sortSelect) sortSelect.value = 'price_changed';
                    } else {
                        showToast('✅ Actualización finalizada: Precios y stock sin cambios.', 5000);
                    }

                    applyFilters();
                    updateGlobalStats();
                    loadCampaigns();
                } else if (!syncStatus.is_syncing && syncStatus.estado === 'error') {
                    clearInterval(syncPollInterval);
                    syncPollInterval = null;
                    if (icon) icon.classList.remove('spinner');
                    showToast('⚠️ Error durante la sincronización.');
                }
            } catch (err) {
                console.error('Error sondeando sincronización:', err);
            }
        }, 2000);

    } catch (e) {
        console.error(e);
        if (icon) icon.classList.remove('spinner');
        showToast('Error al conectar con el servidor');
    }
}

function showToast(msg, duration = 4500) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.innerHTML = msg;
    toast.classList.add('show');
    clearTimeout(toast.timeoutId);
    toast.timeoutId = setTimeout(() => {
        toast.classList.remove('show');
    }, duration);
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>"']/g, function(m) {
        return {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        }[m];
    });
}
