// 予算モニタリング - 静的サイト JavaScript

// グローバル変数
let data = null;
let currentPrefectureFilter = 'all';
let currentMunicipalityFilter = 'all';
let currentKeywordFilter = 'all';
let currentFavoriteFilter = 'all';
let favorites = JSON.parse(localStorage.getItem('budget_favorites') || '[]');

// 府県クラスマッピング
const prefectureClassMap = {
    '滋賀県': 'pref-shiga',
    '京都府': 'pref-kyoto',
    '大阪府': 'pref-osaka',
    '兵庫県': 'pref-hyogo',
    '奈良県': 'pref-nara',
    '和歌山県': 'pref-wakayama'
};

// 初期化
document.addEventListener('DOMContentLoaded', async () => {
    await loadData();
    render();
});

// データ読み込み
async function loadData() {
    try {
        const response = await fetch(`data/items.json?t=${new Date().getTime()}`);
        data = await response.json();
    } catch (error) {
        console.error('データの読み込みに失敗しました:', error);
        data = { items: [], prefectures: [], prefectureMunicipalities: {}, lastUpdated: null };
    }
}

// メインレンダリング
function render() {
    const app = document.getElementById('app');

    // フィルターバーは常に表示
    const prefectures = data && data.prefectures ? data.prefectures : ['滋賀県', '京都府', '大阪府', '兵庫県', '奈良県', '和歌山県'];

    let contentHtml = '';
    if (!data || !data.items || data.items.length === 0) {
        contentHtml = `
            <div class="no-data">
                <p>表示するデータがありません。</p>
                <p>設定ページから自治体を登録し、スクレイピングを実行してください。</p>
            </div>
        `;
    } else {
        contentHtml = `
            <div class="list-header">
                ${data.lastUpdated ? `<span class="last-updated">📅 最終更新: ${data.lastUpdated}</span>` : '<span></span>'}
                <div class="favorite-toggle" id="favorite-filters">
                    <span class="filter-chip active" data-filter="all" onclick="filterByFavorite('all', this)">すべて</span>
                    <span class="filter-chip" data-filter="favorites" onclick="filterByFavorite('favorites', this)">⭐ お気に入りのみ</span>
                </div>
            </div>
            <div class="list-container" id="list-container">
                ${renderItems()}
            </div>
        `;
    }

    // 使用されているキーワードを収集
    const usedKeywords = new Set();
    if (data && data.items) {
        data.items.forEach(item => {
            item.tags.forEach(tag => usedKeywords.add(tag));
        });
    }

    app.innerHTML = `
        <div class="filter-bar">
            <!-- 県別フィルター -->
            <div class="filter-section">
                <span class="filter-label">県別</span>
                <div class="filter-row">
                    <div class="filter-chips" id="prefecture-filters">
                        <span class="filter-chip active" data-filter="all" onclick="filterByPrefecture('all', this)">すべて</span>
                        ${prefectures.map(pref => `
                            <span class="filter-chip" data-filter="${pref}" onclick="filterByPrefecture('${pref}', this)">${pref}</span>
                        `).join('')}
                    </div>
                    <select id="municipality-select" class="municipality-dropdown" onchange="filterByMunicipality(this.value)" disabled>
                        <option value="all">市町村を選択</option>
                    </select>
                </div>
            </div>
            
            <!-- キーワードフィルター -->
            ${usedKeywords.size > 0 ? `
            <div class="filter-section">
                <span class="filter-label">キーワード別</span>
                <div class="filter-chips" id="keyword-filters">
                    <span class="filter-chip active" data-filter="all" onclick="filterByKeyword('all', this)">すべて</span>
                    <span class="filter-chip" data-filter="EXCLUDE_EMPTY" onclick="filterByKeyword('EXCLUDE_EMPTY', this)">キーワードなしを除く</span>
                    ${Array.from(usedKeywords).sort().map(kw => `
                        <span class="filter-chip" data-filter="${kw}" onclick="filterByKeyword('${kw}', this)">${kw}</span>
                    `).join('')}
                </div>
            </div>
            ` : ''}
        </div>
        
        ${contentHtml}
    `;

    // お気に入り状態を復元
    if (data && data.items && data.items.length > 0) {
        restoreFavorites();
    }
}



// アイテムリストのレンダリング
function renderItems() {
    return data.items.map(item => {
        const prefClass = prefectureClassMap[item.prefecture] || '';
        const tagsHtml = item.tags.length > 0
            ? item.tags.map(tag => `<span class="tag">${tag}</span>`).join('')
            : '<span class="tag no-keyword">キーワードなし</span>';

        // 日付フォーマット
        const dateStr = item.date ? item.date.replace(/\//g, '.') : '';

        // 3日以内の新着判定
        let newBadge = '';
        if (item.date) {
            const itemDate = new Date(item.date);
            const now = new Date();
            const diffTime = Math.abs(now - itemDate);
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
            if (diffDays <= 3) {
                newBadge = '<span class="new-badge">NEW</span>';
            }
        }

        return `
            <div class="list-item${newBadge ? ' has-new' : ''}" 
                 data-id="${item.id}" 
                 data-prefecture="${item.prefecture}" 
                 data-municipality="${item.municipality}"
                 data-keywords="${item.tags.join(',')}">
                ${newBadge}
                <div class="item-row-1">
                    <div class="item-date">
                        ${dateStr}
                    </div>
                    <span class="item-municipality ${prefClass}">${item.municipality}</span>
                    <div class="item-title">${item.title}</div>
                </div>
                <div class="item-row-2">
                    <div class="item-tags">${tagsHtml}</div>
                    <div class="item-action">
                        <button class="favorite-btn" onclick="toggleFavorite(this, '${item.id}')" title="お気に入り">
                            <svg class="favorite-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
                            </svg>
                        </button>
                        <a href="${item.url}" target="_blank" class="arrow-btn">
                            <svg class="arrow-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                <path d="M16.172 11L10.808 5.63605L12.222 4.22205L20 12L12.222 19.778L10.808 18.364L16.172 13H4V11H16.172Z" />
                            </svg>
                        </a>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// お気に入り状態の復元
function restoreFavorites() {
    favorites.forEach(id => {
        const btn = document.querySelector(`.list-item[data-id="${id}"] .favorite-btn`);
        if (btn) {
            btn.classList.add('active');
        }
    });
}

// お気に入りトグル
function toggleFavorite(btn, id) {
    const index = favorites.indexOf(id);
    if (index > -1) {
        favorites.splice(index, 1);
        btn.classList.remove('active');
    } else {
        favorites.push(id);
        btn.classList.add('active');
    }
    localStorage.setItem('budget_favorites', JSON.stringify(favorites));

    if (currentFavoriteFilter === 'favorites') {
        applyFilters();
    }
}

// 市町村プルダウン更新
function updateMunicipalityDropdown(prefecture) {
    const select = document.getElementById('municipality-select');
    select.innerHTML = '<option value="all">市町村を選択</option>';

    if (prefecture === 'all') {
        select.disabled = true;
        return;
    }

    select.disabled = false;
    const municipalities = data.prefectureMunicipalities[prefecture] || [];
    municipalities.forEach(m => {
        const option = document.createElement('option');
        option.value = m;
        option.textContent = m;
        select.appendChild(option);
    });
}

// 県フィルター
function filterByPrefecture(value, element) {
    currentPrefectureFilter = value;
    currentMunicipalityFilter = 'all';

    document.querySelectorAll('#prefecture-filters .filter-chip').forEach(chip => {
        chip.classList.remove('active');
    });
    element.classList.add('active');

    updateMunicipalityDropdown(value);
    applyFilters();
}

// 市町村フィルター
function filterByMunicipality(value) {
    currentMunicipalityFilter = value;
    applyFilters();
}

// キーワードフィルター
function filterByKeyword(value, element) {
    currentKeywordFilter = value;

    document.querySelectorAll('#keyword-filters .filter-chip').forEach(chip => {
        chip.classList.remove('active');
    });
    element.classList.add('active');

    applyFilters();
}

// お気に入りフィルター
function filterByFavorite(value, element) {
    currentFavoriteFilter = value;

    document.querySelectorAll('#favorite-filters .filter-chip').forEach(chip => {
        chip.classList.remove('active');
    });
    element.classList.add('active');

    applyFilters();
}

// フィルター適用
function applyFilters() {
    const items = document.querySelectorAll('.list-item');

    items.forEach(item => {
        const prefecture = item.dataset.prefecture;
        const municipality = item.dataset.municipality;
        const keywords = item.dataset.keywords ? item.dataset.keywords.split(',') : [];
        const itemId = item.dataset.id;

        let showByPrefecture = currentPrefectureFilter === 'all' || prefecture === currentPrefectureFilter;
        let showByMunicipality = currentMunicipalityFilter === 'all' || municipality === currentMunicipalityFilter;
        const isKeywordMatch = currentKeywordFilter === 'all'
            ? true
            : currentKeywordFilter === 'EXCLUDE_EMPTY'
                ? keywords.length > 0
                : keywords.includes(currentKeywordFilter);
        let showByFavorite = currentFavoriteFilter === 'all' || favorites.includes(itemId);

        if (showByPrefecture && showByMunicipality && isKeywordMatch && showByFavorite) {
            item.style.display = 'flex';
        } else {
            item.style.display = 'none';
        }
    });
}
