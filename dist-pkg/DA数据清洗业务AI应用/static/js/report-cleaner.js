/**
 * 财务报表清洗 — 前端逻辑
 * 线性流程: 上传 → AI检测 → 提取 → 预览/导出
 */

(function() {
    'use strict';

    let state = {
        filepath: null,
        filename: null,
        sheetNames: [],
        detectionMeta: null,
        extractedData: null,
        reports: [],          // [{sheetName, filename, reportType, columns, data, ...}]
    };

    // ── DOM 引用 ──
    const $ = id => document.getElementById(id);
    const uploadArea = $('report-upload-area');
    const fileInput = $('report-file-input');
    const browseBtn = $('report-browse-btn');
    const fileInfo = $('report-file-info');
    const fileName = $('report-file-name');
    const fileSize = $('report-file-size');
    const removeBtn = $('report-remove-file');
    const configArea = $('report-config-area');
    const sheetSelect = $('report-sheet-select');
    const detectBtn = $('report-detect-btn');
    const uploadError = $('upload-error');

    const cardUpload = $('card-upload');
    const cardDetection = $('card-detection');
    const cardResults = $('card-results');
    const detectionGrid = $('detection-grid');
    const detectionCols = $('detection-cols');
    const detectionSkip = $('detection-skip-keywords');
    const detectionError = $('detection-error');
    const extractBtn = $('extract-btn');
    const retryBtn = $('retry-detect-btn');

    const resultsStats = $('results-stats');
    const resultsTable = $('results-table');
    const extractError = $('extract-error');
    const exportBtn = $('export-btn');
    const resetBtn = $('reset-btn');
    const addReportBtn = $('add-report-btn');

    const globalLoading = $('global-loading');
    const loadingText = $('global-loading-text');

    const cardReconcile = $('card-reconcile');
    const reconcileBtn = $('reconcile-btn');
    const reconcileLoading = $('reconcile-loading');
    const reconcileContainer = $('reconcile-container');
    const reconcileCompanyFilter = $('reconcile-company-filter');
    const reconcileRefreshBtn = $('reconcile-refresh-btn');
    const reconcileBackBtn = $('reconcile-back-btn');
    const reconcileExportBtn = $('reconcile-export-btn');
    const reconcileBalanceBody = $('reconcile-balance-body');
    const reconcileResultBody = $('reconcile-result-body');
    const reconcileSelectAll = $('reconcile-select-all');
    const batchEditBar = $('batch-edit-bar');
    const batchSelectedCount = $('batch-selected-count');
    const batchItemInput = $('batch-item-input');
    const batchApplyBtn = $('batch-apply-btn');
    const batchCancelBtn = $('batch-cancel-btn');
    const reconcileRowCount = $('reconcile-row-count');
    const reconcileStatsLabel = $('reconcile-stats-label');
    const reconcileError = $('reconcile-error');
    const reconcileAiBtn = $('reconcile-ai-btn');
    const reconcileAiAnalysis = $('reconcile-ai-analysis');
    const reconcileAiBody = $('reconcile-ai-body');
    const reconcileAiLoading = $('reconcile-ai-loading');
    const reconcileAiClose = $('reconcile-ai-close');

    let reconcileState = {
        balanceRows: [],       // 完整映射数据（含 report_item 字段）
        reportItems: [],       // 报表项目列表
        companies: [],         // 公司列表
        currentFilter: '',     // 当前公司筛选
        comparison: [],        // 最近一次核对结果
        stats: {},             // 最近一次统计
    };

    // ── 工具函数 ──
    function showLoading(msg) {
        globalLoading.style.display = 'block';
        loadingText.textContent = msg || '处理中...';
    }

    function hideLoading() {
        globalLoading.style.display = 'none';
    }

    function showError(el, msg) {
        el.textContent = msg;
        el.style.display = 'block';
    }

    function hideError(el) {
        el.style.display = 'none';
    }

    function renderImportSummary() {
        const container = document.getElementById('report-import-summary');
        if (!container || state.reports.length === 0) {
            if (container) container.style.display = 'none';
            return;
        }
        const typeLabels = { 'balance_sheet': '资产负债表', 'income_statement': '利润表', 'other': '其他' };
        let html = '<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:12px 16px;">' +
            '<div style="font-size:13px;font-weight:600;color:#166534;margin-bottom:6px;">📋 已导入报表</div>';
        state.reports.forEach((r, i) => {
            html += `<div style="display:flex;align-items:center;gap:6px;padding:3px 0;font-size:13px;">
                <span style="color:#166534;">✓</span>
                <span style="font-weight:600;">${typeLabels[r.reportType] || r.reportType}</span>
                <span style="color:var(--secondary-color);">${escapeHtml(r.filename)}</span>
                <span style="color:var(--secondary-color);font-size:12px;">(${r.row_count} 行)</span>
            </div>`;
        });
        html += '</div>';
        container.innerHTML = html;
        container.style.display = 'block';
    }

    function formatSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    }

    function resetToUpload() {
        state = { filepath: null, filename: null, sheetNames: [], detectionMeta: null, extractedData: null, reports: [] };
        cardDetection.style.display = 'none';
        cardResults.style.display = 'none';
        cardReconcile.style.display = 'none';
        cardUpload.style.display = 'block';
        configArea.style.display = 'none';
        hideError(uploadError);
        hideError(detectionError);
        hideError(extractError);
    }

    function showCard(el) { el.style.display = 'block'; }
    function hideCard(el) { el.style.display = 'none'; }

    // ── 上传文件 ──
    function handleFile(file) {
        if (!file) return;
        const ext = '.' + file.name.split('.').pop().toLowerCase();
        if (!['.xlsx', '.xls'].includes(ext)) {
            showError(uploadError, '仅支持 .xlsx 和 .xls 格式');
            return;
        }

        hideError(uploadError);
        fileName.textContent = file.name;
        fileSize.textContent = formatSize(file.size);
        fileInfo.style.display = 'flex';
        configArea.style.display = 'none';
        state.filename = file.name;

        uploadFile(file);
    }

    async function uploadFile(file) {
        showLoading('正在上传文件...');
        const formData = new FormData();
        formData.append('file', file);

        try {
            const resp = await fetch('/api/report-upload', { method: 'POST', body: formData });
            const data = await resp.json();
            hideLoading();

            if (!data.success) {
                showError(uploadError, data.error || '上传失败');
                return;
            }

            state.filepath = data.filepath;
            state.sheetNames = data.sheets.map(s => s.name);

            // 渲染 sheet 选择
            sheetSelect.innerHTML = '';
            data.sheets.forEach(s => {
                const opt = document.createElement('option');
                opt.value = s.name;
                opt.textContent = `${s.name}（${s.total_rows}行）`;
                sheetSelect.appendChild(opt);
            });

            configArea.style.display = 'block';
        } catch (e) {
            hideLoading();
            showError(uploadError, '网络错误: ' + e.message);
        }
    }

    // ── AI 检测 ──
    async function detectReport() {
        const sheetName = sheetSelect.value;
        if (!sheetName) {
            showError(uploadError, '请选择工作表');
            return;
        }

        showLoading('AI 正在分析报表结构...');
        hideError(detectionError);
        hideError(uploadError);

        try {
            const resp = await fetch('/api/report-detect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sheet_name: sheetName }),
            });
            const data = await resp.json();
            hideLoading();

            if (!data.success) {
                showError(uploadError, data.error || 'AI 检测失败');
                return;
            }

            state.detectionMeta = data;

            // 渲染检测结果
            renderDetection(data);

            hideCard(cardUpload);
            showCard(cardDetection);
        } catch (e) {
            hideLoading();
            showError(uploadError, '网络错误: ' + e.message);
        }
    }

    function renderDetection(meta) {
        // 基本信息
        const labels = {
            'balance_sheet': '资产负债表',
            'income_statement': '利润表',
            'other': '其他'
        };
        const layouts = {
            'left_right_split': '左右分栏',
            'single_side': '单侧列式'
        };

        detectionGrid.innerHTML = `
            <div class="detection-item">
                <div class="label">报表类型</div>
                <div class="value">${labels[meta.report_type] || escapeHtml(meta.report_type)}</div>
            </div>
            <div class="detection-item">
                <div class="label">布局方式</div>
                <div class="value">${layouts[meta.layout_type] || meta.layout_type}</div>
            </div>
            <div class="detection-item">
                <div class="label">表头行数</div>
                <div class="value">${meta.header_rows_count} 行</div>
            </div>
            <div class="detection-item">
                <div class="label">数据区域</div>
                <div class="value">第 ${meta.data_start_row} 行 → 第 ${meta.data_end_row || '?'} 行</div>
            </div>
        `;

        if (meta.company_name) {
            detectionGrid.insertAdjacentHTML('beforeend', `
                <div class="detection-item" style="border-left-color:var(--secondary-color);">
                    <div class="label">公司名称</div>
                    <div class="value">${escapeHtml(meta.company_name)}</div>
                </div>
            `);
        }
        if (meta.report_period) {
            detectionGrid.insertAdjacentHTML('beforeend', `
                <div class="detection-item" style="border-left-color:var(--secondary-color);">
                    <div class="label">报表期间</div>
                    <div class="value">${escapeHtml(meta.report_period)}</div>
                </div>
            `);
        }

        // 列映射
        const stdNames = {
            'project_name': '项目名称',
            'line_no': '行次',
            'period_end': '期末余额',
            'period_begin': '年初余额',
            'month_amount': '本月金额',
            'year_amount': '本年累计金额',
            'last_year_amount': '上年同期累计',
            'ignore': '忽略',
        };
        const sideNames = { 'left': '←左', 'right': '右→', 'center': '中' };

        detectionCols.innerHTML = '';
        (meta.columns || []).forEach(c => {
            if (c.standard_field === 'ignore') return;
            const badge = document.createElement('span');
            badge.className = 'col-badge';
            badge.innerHTML = `
                <span class="col-idx">[${c.index}]</span>
                ${escapeHtml(c.name)}
                <span style="font-weight:normal;color:white;">→</span>
                ${stdNames[c.standard_field] || c.standard_field}
                <span class="col-side">${sideNames[c.side] || ''}</span>
            `;
            detectionCols.appendChild(badge);
        });

        // 跳过关键词
        const keywords = meta.skip_keywords || [];
        detectionSkip.textContent = keywords.join('、') || '（无）';
    }

    // ── 提取数据 ──
    async function extractData() {
        if (!state.detectionMeta) return;

        showLoading('正在提取数据...');
        hideError(extractError);

        try {
            const resp = await fetch('/api/report-extract', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sheet_name: sheetSelect.value,
                    detection_meta: state.detectionMeta,
                }),
            });
            const data = await resp.json();
            hideLoading();

            if (!data.success) {
                showError(extractError, data.error || '提取失败');
                return;
            }

            state.extractedData = data;

            // 保存到多报表列表
            state.reports.push({
                sheetName: sheetSelect.value,
                filename: state.filename,
                reportType: data.report_type || 'unknown',
                columns: data.columns || [],
                data: data.data || [],
                row_count: data.row_count || 0,
                report_period: data.report_period || '',
                company_name: data.company_name || '',
                removed: data.removed || {},
            });

            hideCard(cardDetection);
            renderResults(data);
            showCard(cardResults);
            renderImportSummary();
        } catch (e) {
            hideLoading();
            showError(extractError, '网络错误: ' + e.message);
        }
    }

    function renderResults(data) {
        // 统计
        const removed = data.removed || {};
        const total = data.row_count || 0;
        const removedTotal = (removed.summary || 0) + (removed.signature || 0)
                           + (removed.annotation || 0) + (removed.empty || 0);

        resultsStats.innerHTML = `
            <span class="stat-badge">总行数: ${total}</span>
            <span class="stat-badge">过滤: ${removedTotal} 行</span>
            <span class="stat-badge ${removed.summary > 0 ? 'warning' : ''}">汇总行: ${removed.summary || 0}</span>
            <span class="stat-badge">签名行: ${removed.signature || 0}</span>
            <span class="stat-badge">注释行: ${removed.annotation || 0}</span>
            <span class="stat-badge">空行: ${removed.empty || 0}</span>
        `;

        if (data.report_period) {
            resultsStats.insertAdjacentHTML('beforeend',
                `<span class="stat-badge" style="background:#e0f2fe;color:#075985;">期间: ${escapeHtml(data.report_period)}</span>`);
        }
        if (data.company_name) {
            resultsStats.insertAdjacentHTML('beforeend',
                `<span class="stat-badge" style="background:#e0f2fe;color:#075985;">${escapeHtml(data.company_name)}</span>`);
        }

        // 已导入报表列表（多报表支持）
        renderReportList();

        // 表格
        const columns = data.columns || [];
        const rows = data.data || [];

        let html = '<thead><tr>';
        columns.forEach(c => { html += `<th>${c}</th>`; });
        html += '</tr></thead><tbody>';

        const previewRows = rows.slice(0, 100);
        previewRows.forEach(row => {
            html += '<tr>';
            columns.forEach(c => {
                let val = row[c];
                if (val === '' || val === null || val === undefined) val = '';
                html += `<td>${escapeHtml(String(val))}</td>`;
            });
            html += '</tr>';
        });

        if (rows.length > 100) {
            html += `<tr><td colspan="${columns.length}" style="text-align:center;color:var(--secondary-color);font-style:italic;">
                仅显示前 100 行，共 ${rows.length} 行
            </td></tr>`;
        }

        html += '</tbody>';
        resultsTable.innerHTML = html;
    }

    function renderReportList() {
        const container = document.getElementById('report-list-container') || (() => {
            const div = document.createElement('div');
            div.id = 'report-list-container';
            div.style.cssText = 'margin: 12px 0;';
            resultsStats.parentNode.insertBefore(div, resultsStats.nextSibling);
            return div;
        })();

        const typeLabels = { 'balance_sheet': '资产负债表', 'income_statement': '利润表', 'other': '其他' };
        let html = '<div style="background:#f8f9fa;border-radius:8px;padding:12px 16px;margin-bottom:12px;">' +
            '<div style="font-size:13px;font-weight:600;color:var(--secondary-color);margin-bottom:8px;">📋 已导入报表</div>';
        state.reports.forEach((r, i) => {
            html += `<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #e5e7eb;">
                <span style="background:#166534;color:white;border-radius:50%;width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;">${i+1}</span>
                <span style="font-weight:600;">${typeLabels[r.reportType] || r.reportType}</span>
                <span style="color:var(--secondary-color);font-size:13px;">${escapeHtml(r.filename)}</span>
                <span style="color:var(--secondary-color);font-size:12px;">${r.row_count} 行</span>
            </div>`;
        });
        html += '</div>';
        container.innerHTML = html;
    }

    // ── 导出 Excel ──
    async function exportExcel() {
        if (!state.extractedData) return;

        showLoading('正在生成 Excel...');

        try {
            const resp = await fetch('/api/report-export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sheet_name: sheetSelect.value,
                    detection_meta: state.detectionMeta,
                }),
            });

            if (!resp.ok) {
                const err = await resp.json();
                hideLoading();
                showError(extractError, err.error || '导出失败');
                return;
            }

            // 下载文件
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `报表清洗_${state.filename || 'output'}.xlsx`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            hideLoading();
        } catch (e) {
            hideLoading();
            showError(extractError, '导出失败: ' + e.message);
        }
    }

    // ── 科目余额表核对（可编辑交互版） ──

    async function runReconcile() {
        if (state.reports.length === 0) return;

        // 构造所有已导入报表的数据
        const reportDataList = state.reports.map(r => ({
            data: r.data || [],
            columns: r.columns || [],
            report_type: r.reportType || 'unknown',
            report_period: r.report_period || '',
            company_name: r.company_name || '',
            row_count: r.row_count || 0,
        }));

        reconcileLoading.style.display = 'block';
        reconcileContainer.style.display = 'none';
        hideError(reconcileError);
        showCard(cardReconcile);

        try {
            const resp = await fetch('/api/report-reconciliation', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sheet_name: state.reports[0].sheetName,
                    detection_meta: state.detectionMeta || {},
                    report_data_list: reportDataList,
                }),
            });
            const data = await resp.json();
            reconcileLoading.style.display = 'none';

            if (!data.success) {
                showError(reconcileError, data.error || '核对失败');
                return;
            }

            // 调试信息
            if (data._debug) {
                console.log('[RECONCILE DEBUG]', JSON.stringify(data._debug, null, 2));
            }

            // 保存状态
            reconcileState.balanceRows = data.balance_rows || [];
            reconcileState.reportItems = data.report_items || [];
            reconcileState.companies = data.companies || [];
            reconcileState.currentFilter = '';

            // 填充 datalist 选项
            const datalist = document.getElementById('reconcile-item-datalist');
            datalist.innerHTML = reconcileState.reportItems.map(n =>
                `<option value="${escapeHtml(n)}">`
            ).join('');

            // 渲染
            renderCompanyFilter();
            renderBalanceTable();
            // 初始也跑一次核对
            await refreshReconcile();
            reconcileContainer.style.display = 'block';
        } catch (e) {
            reconcileLoading.style.display = 'none';
            showError(reconcileError, '网络错误: ' + e.message);
        }
    }

    function renderCompanyFilter() {
        reconcileCompanyFilter.innerHTML = '<option value="">全部</option>';
        reconcileState.companies.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c;
            opt.textContent = c;
            reconcileCompanyFilter.appendChild(opt);
        });
    }

    function getFilteredRows() {
        const filter = reconcileCompanyFilter.value;
        if (!filter) return reconcileState.balanceRows;
        return reconcileState.balanceRows.filter(r => r.company === filter);
    }

    function renderBalanceTable() {
        const rows = getFilteredRows();
        reconcileRowCount.textContent = `(${rows.length} 行)`;

        if (rows.length === 0) {
            reconcileBalanceBody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:20px;color:var(--secondary-color);">无数据</td></tr>';
            return;
        }

        // 从核对结果构建“有差异的报表项目”集合
        const diffItems = new Set();
        reconcileState.comparison.forEach(c => {
            if (Math.abs(c.diff || 0) > 0.01) {
                diffItems.add(c.report_item);
            }
        });

        let html = '';
        let rowIndex = 0;
        rows.forEach(r => {
            const amt = formatReconcileNum(r.ending_balance || 0);
            const item = r.report_item || '';
            const isMapped = !!item;
            const isUnmapped = !isMapped;
            const hasDiff = isMapped && diffItems.has(item);

            let rowStyle = '';
            let textColor = '';
            let borderColor = '';
            let bgColor = '';
            if (isUnmapped) {
                rowStyle = 'background:#fef2f2;';
                textColor = 'color:#991b1b;';
                borderColor = '#fecaca';
                bgColor = '#fef2f2';
            } else if (hasDiff) {
                rowStyle = 'background:#fff7ed;';
                textColor = 'color:#9a3412;';
                borderColor = '#fed7aa';
                bgColor = '#fff7ed';
            } else {
                borderColor = '#bbf7d0';
                bgColor = '#f0fdf4';
            }

            const idx = rowIndex++;
            html += `<tr${rowStyle ? ' style="' + rowStyle + '"' : ''}>
                <td style="text-align:center;padding:4px;">
                    <input type="checkbox" class="reconcile-row-checkbox" data-idx="${idx}" style="cursor:pointer;">
                </td>
                <td style="font-size:12px;${textColor}">${escapeHtml(r.account_code || '')}</td>
                <td style="${textColor}">${escapeHtml(r.account_name || '')}</td>
                <td style="text-align:right;${textColor}">${amt}</td>
                <td style="padding:2px 4px;">
                    <input type="text" class="reconcile-item-input"
                        data-idx="${idx}"
                        value="${escapeHtml(item)}"
                        placeholder="输入报表科目..."
                        list="reconcile-item-datalist"
                        style="width:100%;border:1px solid ${borderColor};border-radius:4px;padding:4px 6px;font-size:13px;background:${bgColor};">
                </td>
            </tr>`;
        });
        reconcileBalanceBody.innerHTML = html;

        // 同步 report_item 值回 state 当输入变化时
        reconcileBalanceBody.querySelectorAll('.reconcile-item-input').forEach(inp => {
            inp.addEventListener('input', function() {
                const idx = parseInt(this.dataset.idx);
                const filter = reconcileCompanyFilter.value;
                const rows = filter ? reconcileState.balanceRows.filter(r => r.company === filter) : reconcileState.balanceRows;
                if (rows[idx]) {
                    rows[idx].report_item = this.value;
                }
                const isNowMapped = !!this.value.trim();
                // 更新行背景和文字颜色（实时反映映射状态）
                const tr = this.closest('tr');
                if (tr) {
                    tr.style.background = isNowMapped ? '' : '#fef2f2';
                    const cells = tr.querySelectorAll('td');
                    cells.forEach((td, i) => {
                        if (i >= 1 && i <= 3) { // 编号、名称、余额三列
                            td.style.color = isNowMapped ? '' : '#991b1b';
                        }
                    });
                }
                this.style.borderColor = isNowMapped ? '#bbf7d0' : '#fecaca';
                this.style.background = isNowMapped ? '#f0fdf4' : '#fef2f2';
            });
        });

        // 复选框：选中状态变化时更新批量编辑栏
        const checkboxes = reconcileBalanceBody.querySelectorAll('.reconcile-row-checkbox');
        checkboxes.forEach(cb => {
            cb.addEventListener('change', updateBatchBar);
        });
    }

    // 全选复选框
    if (reconcileSelectAll) {
        reconcileSelectAll.addEventListener('change', function() {
            const checked = this.checked;
            reconcileBalanceBody.querySelectorAll('.reconcile-row-checkbox').forEach(cb => {
                cb.checked = checked;
            });
            updateBatchBar();
        });
    }

    function updateBatchBar() {
        const checked = reconcileBalanceBody.querySelectorAll('.reconcile-row-checkbox:checked');
        const count = checked.length;
        if (count > 0) {
            batchEditBar.style.display = 'flex';
            batchSelectedCount.textContent = `已选 ${count} 行`;
        } else {
            batchEditBar.style.display = 'none';
            if (reconcileSelectAll) reconcileSelectAll.checked = false;
        }
    }

    // 批量应用
    batchApplyBtn.addEventListener('click', function() {
        const val = batchItemInput.value.trim();
        if (!val) return;
        const checked = reconcileBalanceBody.querySelectorAll('.reconcile-row-checkbox:checked');
        const filter = reconcileCompanyFilter.value;
        const rows = filter ? reconcileState.balanceRows.filter(r => r.company === filter) : reconcileState.balanceRows;
        checked.forEach(cb => {
            const idx = parseInt(cb.dataset.idx);
            if (rows[idx]) {
                rows[idx].report_item = val;
            }
        });
        // 刷新左栏
        renderBalanceTable();
    });

    // 批量取消
    batchCancelBtn.addEventListener('click', function() {
        batchItemInput.value = '';
        reconcileBalanceBody.querySelectorAll('.reconcile-row-checkbox:checked').forEach(cb => {
            cb.checked = false;
        });
        updateBatchBar();
    });

    async function refreshReconcile() {
        // 收集当前全部映射
        const mappings = reconcileState.balanceRows.map(r => ({
            account_code: r.account_code,
            account_name: r.account_name,
            ending_balance: r.ending_balance,
            report_item: r.report_item || '',
        }));

        // 构造所有已导入报表的数据
        const reportDataList = state.reports.map(r => ({
            data: r.data || [],
            columns: r.columns || [],
            report_type: r.reportType || 'unknown',
        }));

        try {
            const resp = await fetch('/api/report-reconciliation', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sheet_name: state.reports[0]?.sheetName || '',
                    detection_meta: state.detectionMeta || {},
                    mappings: mappings,
                    report_data_list: reportDataList,
                }),
            });
            const data = await resp.json();
            if (!data.success) {
                showError(reconcileError, data.error || '核对失败');
                return;
            }
            hideError(reconcileError);
            reconcileState.comparison = data.comparison || [];
            reconcileState.stats = data.stats || {};
            renderResultTable();

            // 重新渲染左表（因为映射可能变了）
            renderBalanceTable();
        } catch (e) {
            showError(reconcileError, '网络错误: ' + e.message);
        }
    }

    function renderResultTable() {
        const comparison = reconcileState.comparison;
        const stats = reconcileState.stats;

        reconcileStatsLabel.textContent = `差异 ${stats.difference || 0} | 匹配率 ${stats.match_rate || 0}%`;

        if (comparison.length === 0) {
            reconcileResultBody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:30px;color:var(--secondary-color);">暂无核对数据</td></tr>';
            return;
        }

        let html = '';
        comparison.forEach(item => {
            const diff = item.diff || 0;
            const isDiff = Math.abs(diff) > 0.01;
            const icon = item.match_type === 'mapped' ? '' :
                        item.match_type === 'report_only' ? '📋' : '⚠️';
            const accounts = item.matched_accounts || [];
            const titleAttr = accounts.length > 0
                ? accounts.slice(0, 10).map(a => `${a.code} ${a.name}: ${formatReconcileNum(a.amount)}`).join('\\n')
                : '';

            const iconTitle = item.match_type === 'report_only'
                ? '仅报表有此项目，科目余额表中无对应科目'
                : item.match_type === 'unmatched'
                ? '此科目余额未映射到报表项目'
                : '已匹配';
            html += `<tr${isDiff ? ' style="background:#fef2f2;"' : ''}>
                <td title="${iconTitle}">${icon} ${escapeHtml(item.report_item || '')}</td>
                <td style="text-align:right;">${formatReconcileNum(item.report_amount || 0)}</td>
                <td style="text-align:right;">${formatReconcileNum(item.balance_amount || 0)}</td>
                <td style="text-align:right;font-weight:600;color:${isDiff ? '#dc2626' : '#166534'};" title="${escapeHtml(titleAttr)}">${diff >= 0 ? '+' : ''}${diff.toFixed(2)}</td>
            </tr>`;
        });
        reconcileResultBody.innerHTML = html;
    }

    function formatReconcileNum(num) {
        if (num == null) return '0.00';
        return Number(num).toFixed(2).replace(/\d(?=(\d{3})+\.)/g, '$&,');
    }

    function escapeHtml(text) {
        if (!text) return '';
        const d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML;
    }

    // ── 事件绑定 ──
    // 文件选择
    browseBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        fileInput.click();
    });
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) handleFile(e.target.files[0]);
    });

    // 拖拽
    uploadArea.addEventListener('dragover', (e) => { e.preventDefault(); uploadArea.classList.add('dragover'); });
    uploadArea.addEventListener('dragleave', () => { uploadArea.classList.remove('dragover'); });
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0]);
    });

    // 移除文件
    removeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        fileInput.value = '';
        fileInfo.style.display = 'none';
        configArea.style.display = 'none';
        state.filepath = null;
    });

    // AI 检测
    detectBtn.addEventListener('click', detectReport);

    // 提取
    extractBtn.addEventListener('click', extractData);

    // 重新检测
    retryBtn.addEventListener('click', () => {
        hideCard(cardDetection);
        showCard(cardUpload);
    });

    // 导出
    exportBtn.addEventListener('click', exportExcel);

    // 核对科目余额表
    reconcileBtn.addEventListener('click', runReconcile);

    // 添加另一张报表
    addReportBtn.addEventListener('click', () => {
        hideCard(cardResults);
        showCard(cardUpload);
        state.detectionMeta = null;
        state.extractedData = null;
        renderImportSummary();
    });

    // 刷新核对
    reconcileRefreshBtn.addEventListener('click', refreshReconcile);

    // 公司筛选 → 重新渲染左表
    reconcileCompanyFilter.addEventListener('change', () => {
        renderBalanceTable();
    });

    // AI 差异分析
    reconcileAiBtn.addEventListener('click', async () => {
        if (!reconcileState.comparison || reconcileState.comparison.length === 0) {
            showError(reconcileError, '暂无核对数据');
            return;
        }
        reconcileAiAnalysis.style.display = 'block';
        reconcileAiLoading.style.display = 'block';
        reconcileAiBody.textContent = '';
        hideError(reconcileError);

        const mappings = reconcileState.balanceRows.map(r => ({
            account_code: r.account_code,
            account_name: r.account_name,
            ending_balance: r.ending_balance,
            report_item: r.report_item || '',
        }));

        try {
            const resp = await fetch('/api/report-reconciliation/ai-analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    comparison: reconcileState.comparison,
                    mappings: mappings,
                }),
            });
            const data = await resp.json();
            reconcileAiLoading.style.display = 'none';
            if (data.success && data.analysis) {
                reconcileAiBody.textContent = data.analysis;
            } else {
                reconcileAiBody.textContent = '分析失败: ' + (data.error || '未知错误');
            }
        } catch (e) {
            reconcileAiLoading.style.display = 'none';
            reconcileAiBody.textContent = '网络错误: ' + e.message;
        }
    });

    // 关闭 AI 分析面板
    reconcileAiClose.addEventListener('click', () => {
        reconcileAiAnalysis.style.display = 'none';
    });

    // 导出核对结果
    reconcileExportBtn.addEventListener('click', async () => {
        const mappings = reconcileState.balanceRows.map(r => ({
            account_code: r.account_code,
            account_name: r.account_name,
            ending_balance: r.ending_balance,
            report_item: r.report_item || '',
        }));
        const reportDataList = state.reports.map(r => ({
            data: r.data || [],
            columns: r.columns || [],
            report_type: r.reportType || 'unknown',
        }));
        try {
            const resp = await fetch('/api/report-reconciliation/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sheet_name: state.reports[0]?.sheetName || '',
                    detection_meta: state.detectionMeta || {},
                    mappings: mappings,
                    report_data_list: reportDataList,
                }),
            });
            if (!resp.ok) {
                const err = await resp.json();
                showError(reconcileError, err.error || '导出失败');
                return;
            }
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = '核对结果.xlsx';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (e) {
            showError(reconcileError, '导出失败: ' + e.message);
        }
    });

    // 返回预览
    reconcileBackBtn.addEventListener('click', () => {
        hideCard(cardReconcile);
    });

    // 重新上传
    resetBtn.addEventListener('click', resetToUpload);

})();
