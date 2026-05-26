from flask import Flask, render_template, request, session, jsonify, send_file, url_for, redirect, Response
import os
import time
import uuid
import json as json_module
import re
import numpy as np
from config import Config

# 导入模块
from modules.data_processor import DataProcessor
from modules.ai_codegen import AICodeGenerator
from modules.duckdb_engine import DuckDBEngine
from modules.integrity_checker import IntegrityChecker
from modules.mapping_history import save_mapping, find_match
from modules.audit_trail import log_generate, log_execute
from modules.preset_rules import get_rules, get_packs, get_custom_rules, get_rule_by_id, apply_rule, save_rule, delete_rule
from modules.sampling import get_methods, generate_sql
from modules.crypto_utils import encrypt as crypto_encrypt, decrypt as crypto_decrypt

# 用于将 session 中的映射（{标准字段名: 源字段名}）转换为前端渲染格式（{stdFieldId: 源字段名}）
JOURNAL_NAME_TO_ID = {f['name']: f['id'] for f in [
    {"id": "date", "name": "日期"},
    {"id": "summary", "name": "摘要"},
    {"id": "account_code", "name": "科目编号"},
    {"id": "subject", "name": "科目名称"},
    {"id": "company", "name": "公司名"},
    {"id": "debit", "name": "借方"},
    {"id": "credit", "name": "贷方"},
    {"id": "amount", "name": "金额"},
    {"id": "voucher_no", "name": "凭证号"},
    {"id": "department", "name": "部门"},
    {"id": "person", "name": "制单人"},
    {"id": "direction", "name": "方向"},
]}
BALANCE_NAME_TO_ID = {f['name']: f['id'] for f in [
    {"id": "company", "name": "公司名"},
    {"id": "account_code", "name": "科目编号"},
    {"id": "account_name", "name": "科目名称"},
    {"id": "beginning_debit", "name": "期初借方"},
    {"id": "beginning_credit", "name": "期初贷方"},
    {"id": "beginning", "name": "期初余额"},
    {"id": "ending_debit", "name": "期末借方"},
    {"id": "ending_credit", "name": "期末贷方"},
    {"id": "ending", "name": "期末余额"},
    {"id": "beginning_direction", "name": "期初余额方向"},
    {"id": "ending_direction", "name": "期末余额方向"},
]}

app = Flask(__name__)
app.config.from_object(Config)

# 确保上传目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 初始化Flask-Session（使用服务端文件存储，避免客户端Cookie大小限制）
from flask_session import Session
Session(app)

app.secret_key = Config.SECRET_KEY


def _json_safe(obj):
    """递归转换numpy类型为原生Python类型，确保JSON序列化安全"""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return _json_safe(obj.tolist())
    return obj


def get_duckdb_engine():
    """获取或创建当前会话的 DuckDB 引擎"""
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    db_dir = app.config['DUCKDB_DIR']
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, f"{session['session_id']}.db")
    if 'duckdb_engines' not in app.extensions:
        app.extensions['duckdb_engines'] = {}
    sid = session['session_id']
    if sid not in app.extensions['duckdb_engines']:
        app.extensions['duckdb_engines'][sid] = DuckDBEngine(db_path)
    return app.extensions['duckdb_engines'][sid]


def cleanup_session_db():
    """清理当前会话的 DuckDB 数据（引擎 + 数据库文件 + 会话标记）"""
    sid = session.get('session_id')
    if not sid:
        app.logger.warning("[CLEANUP] 无 session_id，跳过清理")
        return

    # 从缓存中移除并关闭/删除引擎
    engines = app.extensions.get('duckdb_engines', {})
    engine = engines.pop(sid, None)
    if engine:
        engine.cleanup()

    # 确保数据库文件被删除（即使引擎清理失败）
    db_path = os.path.join(app.config['DUCKDB_DIR'], f"{sid}.db")
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            app.logger.info(f"[CLEANUP] 已删除数据库文件: {db_path}")
        except Exception as e:
            app.logger.error(f"[CLEANUP] 数据库文件删除失败: {e}")

    # 重置会话中的 DuckDB 相关标记
    session.pop('duckdb_imported', None)
    app.logger.info(f"[CLEANUP] 会话 {sid} DuckDB 数据已清理")


@app.route('/')
def index():
    """主页面"""
    return render_template('index.html')

@app.route('/debug/setup-demo')
def debug_setup_demo():
    """临时：为截图预先配置会话数据"""
    import pandas as pd
    from modules.data_processor import DataProcessor

    je_path = "/Users/evelynn/Desktop/EY AI/成都je.xlsx"
    tb_path = "/Users/evelynn/Desktop/EY AI/成都tb.xlsx"

    if os.path.exists(je_path):
        p = DataProcessor(je_path)
        session['filepath'] = je_path
        session['data_info'] = p.process()

    if os.path.exists(tb_path):
        p = DataProcessor(tb_path)
        session['balance_filepath'] = tb_path
        session['balance_data_info'] = p.process()

    session['field_mapping'] = {
        "日期": "Effective Date",
        "摘要": "JE Description",
        "科目编号": "GL Account Number",
        "科目名称": "GL Account Name",
        "金额": "Functional Amount",
        "凭证号": "JE NUMBER",
        "公司名": "Business Unit Name",
        "借方": "Functional Debit Amount",
        "贷方": "Functional Credit Amount",
        "部门": "Business Unit",
        "制单人": "Preparer"
    }
    session['balance_field_mapping'] = {
        "公司名": "Business Unit Name",
        "科目编号": "GL Account Number",
        "科目名称": "GL Account Name",
        "期初余额": "期初",
        "期末余额": "期末"
    }

    data_info = session.get('data_info', {})
    if data_info:
        rev = {v: k for k, v in session['field_mapping'].items()}
        mapped = []
        for f in data_info.get('fields', []):
            fn = f.get('name', '')
            if fn in rev:
                mf = f.copy()
                mf['name'] = rev[fn]
                mf['original_name'] = fn
                mapped.append(mf)
            else:
                mapped.append(f.copy())
        data_info['mapped_fields'] = mapped
        preview = data_info.get('preview', [])
        if preview:
            mp = []
            for row in preview:
                mr = {}
                for k, v in row.items():
                    mr[rev.get(k, k)] = v
                mp.append(mr)
            data_info['mapped_preview'] = mp
        session['data_info'] = data_info

    balance_info = session.get('balance_data_info', {})
    if balance_info:
        rev = {v: k for k, v in session['balance_field_mapping'].items()}
        mapped = []
        for f in balance_info.get('fields', []):
            fn = f.get('name', '')
            if fn in rev:
                mf = f.copy()
                mf['name'] = rev[fn]
                mf['original_name'] = fn
                mapped.append(mf)
            else:
                mapped.append(f.copy())
        balance_info['mapped_fields'] = mapped
        preview = balance_info.get('preview', [])
        if preview:
            mp = []
            for row in preview:
                mr = {}
                for k, v in row.items():
                    mr[rev.get(k, k)] = v
                mp.append(mr)
            balance_info['mapped_preview'] = mp
        session['balance_data_info'] = balance_info

    return redirect(url_for('field_mapper_page'))

@app.route('/intro')
def intro_page():
    """产品介绍页面"""
    return render_template('intro.html')

@app.route('/upload', methods=['GET'])
def upload_page():
    """文件上传页面"""
    # 清理 DuckDB 数据和会话状态
    cleanup_session_db()
    session.pop('balance_data_info', None)
    session.pop('balance_filepath', None)
    session.pop('data_info', None)
    session.pop('filepath', None)
    session.pop('field_mapping', None)
    session.pop('balance_field_mapping', None)
    session.pop('integrity_results', None)
    session.pop('last_execution_result', None)
    session.pop('pending_filepath', None)
    session.pop('pending_filename', None)
    session.pop('upload_options', None)
    return render_template('upload.html')

@app.route('/field-mapper', methods=['GET'])
def field_mapper_page():
    """字段映射页面（包含序时账和科目余额表映射）"""
    data_info = session.get('data_info')
    if not data_info:
        return redirect(url_for('upload_page'))

    if not session.get('api_key'):
        return redirect(url_for('api_config_page'))

    balance_data_info = session.get('balance_data_info')
    has_balance = bool(balance_data_info)

    # 检测是否有预填的历史映射（来自 apply-mapping-history）
    prefilled_journal = None
    prefilled_balance = None
    if session.pop('mapping_prefilled', None):
        mapping = session.get('field_mapping', {})
        if mapping:
            prefilled_journal = {}
            for std_name, source_name in mapping.items():
                fid = JOURNAL_NAME_TO_ID.get(std_name)
                if fid:
                    prefilled_journal[fid] = source_name
        balance_mapping = session.get('balance_field_mapping', {})
        if balance_mapping:
            prefilled_balance = {}
            for std_name, source_name in balance_mapping.items():
                fid = BALANCE_NAME_TO_ID.get(std_name)
                if fid:
                    prefilled_balance[fid] = source_name

    return render_template('field-mapper.html',
                         data_info=data_info,
                         balance_data_info=balance_data_info,
                         has_balance_data=has_balance,
                         prefilled_journal_mapping=prefilled_journal,
                         prefilled_balance_mapping=prefilled_balance)

@app.route('/balance-mapper', methods=['GET'])
def balance_mapper_page():
    """科目余额表字段映射已合并到字段映射页面"""
    return redirect(url_for('field_mapper_page'))

@app.route('/integrity-test', methods=['GET'])
def integrity_test_page():
    """完整性测试页面"""
    if 'data_info' not in session:
        return redirect(url_for('upload_page'))
    return render_template('integrity-test.html')

@app.route('/api/upload-balance', methods=['POST'])
def upload_balance_file():
    """API: 上传科目余额表（支持 sheet 选择和 header row 指定）"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '没有选择文件'})

    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': '没有选择文件'})

    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': '不支持的文件类型'})

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'balance_' + file.filename)
    file.save(filepath)

    # 解析可选参数：sheet_name 和 header_row
    sheet_name = request.form.get('sheet_name') or None
    header_row_raw = request.form.get('header_row')
    header_row = int(header_row_raw) - 1 if header_row_raw and header_row_raw.isdigit() else None

    try:
        processor = DataProcessor(filepath)
        data_info = processor.process(
            sheet_name=sheet_name if sheet_name and sheet_name != '__csv__' else None,
            header_row=header_row,
        )
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"科目余额表处理失败详情: {error_details}")
        return jsonify({'success': False, 'error': f'科目余额表处理失败: {str(e)}'})

    session['balance_filepath'] = filepath
    session['balance_data_info'] = data_info
    session['balance_upload_options'] = {'sheet_name': sheet_name, 'header_row': header_row}

    return jsonify(data_info)

@app.route('/api/configure-balance-fields', methods=['POST'])
def configure_balance_fields():
    """API: 配置科目余额表字段映射"""
    data = request.json
    field_mapping = data.get('field_mapping')

    if not field_mapping:
        return jsonify({'success': False, 'error': '字段映射不能为空'})

    session['balance_field_mapping'] = field_mapping

    return jsonify({
        'success': True,
        'message': '科目余额表字段映射已保存'
    })

@app.route('/api/integrity-test/run', methods=['POST'])
def run_integrity_tests():
    """API: 运行完整性测试（支持反结转和末级科目模式）"""
    try:
        data = request.get_json(silent=True) or {}
        reverse_cf = data.get('reverse_carry_forward', False)
        leaf_accts = data.get('leaf_accounts', False)

        engine = get_duckdb_engine()
        table_name = 'data' if engine.table_exists('data') else None
        balance_table = 'balance_data' if engine.table_exists('balance_data') else None

        if not table_name:
            return jsonify({'success': False, 'error': '序时账数据为空，请先上传并配置字段映射'})

        checker = IntegrityChecker(engine, journal_table=table_name, balance_table=balance_table)
        results = checker.run_all(reverse_carry_forward=reverse_cf, leaf_accounts=leaf_accts)

        session['integrity_results'] = results
        return jsonify(results)

    except Exception as e:
        import traceback
        app.logger.error(f"[INTEGRITY TEST ERROR] {str(e)}\n{traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': f'完整性测试执行失败: {str(e)}'
        })

@app.route('/api/integrity-test/results', methods=['GET'])
def get_integrity_results():
    """API: 获取上次完整性测试结果"""
    results = session.get('integrity_results')
    if not results:
        return jsonify({'success': False, 'error': '没有完整性测试结果'})
    return jsonify(results)

@app.route('/api/integrity-test/export', methods=['POST'])
def export_integrity_results():
    """API: 导出完整性测试结果为Excel文件（支持反结转和末级科目）"""
    try:
        data = request.get_json(silent=True) or {}
        reverse_cf = data.get('reverse_carry_forward', False)
        leaf_accts = data.get('leaf_accounts', False)

        # 获取 DuckDB 引擎
        engine = get_duckdb_engine()
        table_name = 'data' if engine.table_exists('data') else None
        balance_table = 'balance_data' if engine.table_exists('balance_data') else None

        if not table_name:
            return jsonify({'success': False, 'error': '序时账数据为空，请先上传并配置字段映射'})

        # 通过 IntegrityChecker 生成数据（DuckDB SQL 聚合）
        checker = IntegrityChecker(engine, journal_table=table_name, balance_table=balance_table)
        report = checker.export_report(reverse_carry_forward=reverse_cf, leaf_accounts=leaf_accts)

        import io
        import pandas as pd
        output = io.BytesIO()

        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # ====== Sheet 1: 序时账完整性 ======
            journal_df = report.get('journal')
            if journal_df is not None and not journal_df.empty:
                total_amount = round(journal_df['汇总发生额'].sum(), 2)
                info_rows = pd.DataFrame([
                    {'指标': '汇总金额', '值': total_amount},
                    {'指标': '凭证分组数', '值': len(journal_df)},
                ])
                info_rows.to_excel(writer, sheet_name='序时账完整性', index=False)
                journal_df.to_excel(writer, sheet_name='序时账完整性', index=False, startrow=4)
            else:
                pd.DataFrame([{'提示': '无线程账数据或缺少必要字段'}]) \
                    .to_excel(writer, sheet_name='序时账完整性', index=False)

            # ====== Sheet 2: 科目余额表完整性 ======
            balance_df = report.get('balance')
            if balance_df is not None and not balance_df.empty:
                info_rows = pd.DataFrame([
                    {'指标': '期初余额合计', '值': round(balance_df['期初余额'].sum(), 2)},
                    {'指标': '期末余额合计', '值': round(balance_df['期末余额'].sum(), 2)},
                    {'指标': '发生额合计(期末-期初)', '值': round(balance_df['发生额'].sum(), 2)},
                    {'指标': '是否归零', '值': '是' if abs(balance_df['发生额'].sum()) < 0.01 else f'否（差额{round(balance_df["发生额"].sum(), 2)}）'},
                    {'指标': '科目汇总数', '值': len(balance_df)},
                ])

                # 反结转模式：额外展示调整信息
                if report.get('reverse_carry_forward_applied') and '结转损益金额' in balance_df.columns:
                    cf_total = round(balance_df['结转损益金额'].sum(), 2)
                    cf_info_row = pd.DataFrame([{'指标': '结转损益调整额', '值': cf_total}])
                    info_rows = pd.concat([info_rows, cf_info_row], ignore_index=True)

                info_rows.to_excel(writer, sheet_name='科目余额表完整性', index=False)
                balance_df.to_excel(writer, sheet_name='科目余额表完整性', index=False, startrow=len(info_rows) + 2)
            else:
                pd.DataFrame([{'提示': '无科目余额表数据或缺少必要字段'}]) \
                    .to_excel(writer, sheet_name='科目余额表完整性', index=False)

            # ====== Sheet 3: 交叉验证 ======
            cross_df = report.get('cross_validation')
            if cross_df is not None and not cross_df.empty:
                cross_df = cross_df.fillna(0)
                # 确保所有关键列都有值
                for col in ['序时账发生额', '科目余额表发生额', '差异']:
                    if col in cross_df.columns:
                        cross_df[col] = pd.to_numeric(cross_df[col], errors='coerce').fillna(0)

                info_rows = pd.DataFrame([
                    {'指标': '序时账发生额合计', '值': round(cross_df['序时账发生额'].sum(), 2)},
                    {'指标': '余额表发生额合计', '值': round(cross_df['科目余额表发生额'].sum(), 2)},
                    {'指标': '差异绝对值合计', '值': round(cross_df['差异'].abs().sum(), 2)},
                    {'指标': '汇总科目数', '值': len(cross_df)},
                    {'指标': '完全一致数', '值': int((cross_df['差异'].abs() <= 0.01).sum())},
                    {'指标': '存在差异数', '值': int((cross_df['差异'].abs() > 0.01).sum())},
                ])
                info_rows.to_excel(writer, sheet_name='交叉验证', index=False)

                # 列顺序整理
                preferred_order = ['公司名', '科目编号', '科目名称', '科目余额表期初',
                                   '科目余额表期末', '科目余额表发生额', '序时账发生额', '差异']
                available = [c for c in preferred_order if c in cross_df.columns]
                others = [c for c in cross_df.columns if c not in preferred_order]
                cross_df = cross_df[available + others]

                cross_df.to_excel(writer, sheet_name='交叉验证', index=False, startrow=6)
            else:
                pd.DataFrame([{'提示': '交叉验证无法执行：科目余额表数据为空或缺少必要字段（需含：公司名、科目编号、科目名称、期初余额、期末余额），请确认已正确上传并映射科目余额表'}]) \
                    .to_excel(writer, sheet_name='交叉验证', index=False)

        output.seek(0)
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='完整性测试结果.xlsx'
        )

    except Exception as e:
        import traceback
        app.logger.error(f"[EXPORT ERROR] {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'导出失败: {str(e)}'})


@app.route('/api/integrity-test/ai-analyze', methods=['POST'])
def ai_analyze_integrity():
    """AI 分析完整性测试异常结果 — 从审计视角分析原因并给出建议"""
    results = session.get('integrity_results')
    api_key = session.get('api_key')

    if not results:
        return jsonify({'success': False, 'error': '没有完整性测试结果'})
    if not api_key:
        return jsonify({'success': False, 'error': '请先配置 API Key'})
    if results.get('all_passed'):
        return jsonify({'success': False, 'error': '所有测试均已通过'})

    try:
        provider = session.get('ai_provider', 'deepseek')
        model = session.get('ai_model')
        plain_key = crypto_decrypt(api_key, Config.SECRET_KEY)
        provider_config = Config.AI_PROVIDERS.get(provider, Config.AI_PROVIDERS["deepseek"])
        api_url = provider_config["api_url"]
        model_name = model or provider_config["model"]

        # ---- 构建 prompt ----
        lines = [
            "你是一名资深的财务审计专家。以下是财务数据完整性测试的结果，请从审计专业角度逐项分析异常原因，并给出后续建议。",
            "",
            "## 测试汇总",
        ]
        summary = results.get('summary', {})
        lines.append(f"- 总测试数: {summary.get('total', 3)}")
        lines.append(f"- 完成: {summary.get('completed', 0)}  错误: {summary.get('errors', 0)}  跳过: {summary.get('skipped', 0)}")
        if results.get('reverse_carry_forward_applied'):
            lines.append("- 已启用反结转模式")
        if results.get('leaf_accounts_applied'):
            lines.append("- 已启用末级科目筛选")

        cf_info = results.get('carry_forward_info')
        if cf_info and cf_info.get('error'):
            lines.append(f"\n⚠ 反结转执行异常: {cf_info['error']}")
        lines.append("")

        for test_key, test_label in [
            ('journal_test', '测试一：序时账完整性'),
            ('balance_test', '测试二：科目余额表完整性'),
            ('cross_test', '测试三：交叉验证'),
        ]:
            test = results.get('results', {}).get(test_key, {})
            if not test or test.get('status') != 'completed' or test.get('passed'):
                continue

            details = test.get('details', {})
            lines.append(f"### {test_label}")
            lines.append(f"说明: {test.get('message', '')}")

            if test_key == 'journal_test':
                lines.append(f"汇总金额: {details.get('total_amount', 0)}")
                lines.append(f"正数/负数/零值分组: {details.get('positive_groups', 0)} / {details.get('negative_groups', 0)} / {details.get('zero_groups', 0)}")
                preview = details.get('groups_preview', [])
                non_zero = [g for g in preview if abs(g.get('汇总发生额', 0) or 0) > 0.01]
                if non_zero:
                    lines.append(f"非零分组（前 {min(10, len(non_zero))} 条）：")
                    for g in non_zero[:10]:
                        lines.append(f"  公司:{g.get('公司名','')} 凭证:{g.get('凭证号','')} 日期:{g.get('日期','')} 金额:{g.get('汇总发生额',0)}")
                    total_groups = details.get('total_groups', 0)
                    if total_groups > 10:
                        lines.append(f"  ...共 {total_groups} 个分组")

            elif test_key == 'balance_test':
                lines.append(f"期初余额合计: {details.get('total_beginning', 0)}")
                lines.append(f"期末余额合计: {details.get('total_ending', 0)}")
                lines.append(f"发生额合计(期末-期初): {details.get('total_occurrence', 0)}")
                lines.append(f"发生额归零检查: {'通过' if details.get('balance_check_passed') else '异常'}")

            elif test_key == 'cross_test':
                lines.append(f"汇总科目数: {details.get('total_accounts', 0)}")
                lines.append(f"差异数量: {details.get('difference_count', 0)}")
                lines.append(f"仅有序时账: {details.get('only_in_journal', 0)}")
                lines.append(f"仅有余额表: {details.get('only_in_balance', 0)}")
                lines.append(f"序时账发生额合计: {details.get('journal_total_amount', 0)}")
                lines.append(f"余额表发生额合计: {details.get('balance_total_occurrence', 0)}")
                diff_records = details.get('diff_records', [])
                if diff_records:
                    lines.append(f"差异明细（前 {min(10, len(diff_records))} 条，共 {details.get('difference_count', 0)} 条）：")
                    for r in diff_records[:10]:
                        lines.append(f"  公司:{r.get('公司名','')} 科目:{r.get('科目编号','')} {r.get('科目名称','')}  序时账发生额:{r.get('序时账发生额',0)}  余额表发生额:{r.get('余额表发生额',0)}  差异:{r.get('差异',0)}")
            lines.append("")

        lines.extend([
            "请按以下格式输出分析结果，每个有异常的测试单独分析：",
            "",
            "### [测试名称]",
            "**异常情况**：（简要描述问题）",
            "**可能原因**：（从审计专业视角分析，例如）",
            "- 财务系统导出问题（导出范围不完整、借贷方向不一致、未包含所有期间等）",
            "- 数据自身问题（某月未做损益结转、凭证借贷不平时手工调账、缺少部分科目等）",
            "- 用户配置问题（字段映射错误、期初期末余额方向未正确处理、反结转条件不适配等）",
            "- 会计处理差异（SAP/金蝶/用友等不同系统的特有处理方式）",
            "**建议后续操作**：（列出 1-3 条可操作的审计建议）",
            "",
            "注意：已通过或跳过的测试不要分析。语言专业简洁，用中文。",
        ])
        prompt = "\n".join(lines)

        # ---- 调用 AI ----
        import requests as http_req
        headers = {
            "Authorization": f"Bearer {plain_key}",
            "Content-Type": "application/json",
        }
        req_data = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "你是一名资深的财务审计专家，擅长从审计视角分析财务数据问题。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 2000,
        }
        resp = http_req.post(api_url, headers=headers, json=req_data, timeout=60)
        if resp.status_code != 200:
            return jsonify({'success': False, 'error': f'AI 请求失败: {resp.status_code}'})

        content = resp.json()['choices'][0]['message']['content'].strip()
        return jsonify({'success': True, 'analysis': content})

    except Exception as e:
        import traceback
        app.logger.error(f"[AI-ANALYZE-INTEGRITY] {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'AI 分析失败: {str(e)}'})


@app.route('/api/configure-fields', methods=['POST'])
def configure_fields():
    """API: 配置字段映射（序时账 + 科目余额表）"""
    data = request.json
    field_mapping = data.get('field_mapping')
    balance_field_mapping = data.get('balance_field_mapping')

    if not field_mapping:
        return jsonify({'success': False, 'error': '序时账字段映射不能为空'})

    # 存储序时账映射
    session['field_mapping'] = field_mapping
    app.logger.info(f"[CONFIGURE_FIELDS] field_mapping received: {field_mapping}")

    # 存储手动填写的字段（如手动输入的公司名）
    manual_fills = data.get('manual_fills', {})
    balance_manual_fills = data.get('balance_manual_fills', {})
    session['manual_fills'] = manual_fills
    session['balance_manual_fills'] = balance_manual_fills
    if manual_fills:
        app.logger.info(f"[CONFIGURE_FIELDS] manual_fills: {manual_fills}")
    if balance_manual_fills:
        app.logger.info(f"[CONFIGURE_FIELDS] balance_manual_fills: {balance_manual_fills}")

    # 更新 data_info 中的 mapped_fields 和 mapped_preview
    data_info = session.get('data_info', {})
    app.logger.info(f"[CONFIGURE_FIELDS] data_info keys before: {list(data_info.keys()) if data_info else 'EMPTY'}")
    if data_info and field_mapping:
        reverse_mapping = {v: k for k, v in field_mapping.items()}
        app.logger.info(f"[CONFIGURE_FIELDS] reverse_mapping: {reverse_mapping}")

        # 映射字段信息
        mapped_fields = []
        for field in data_info.get('fields', []):
            field_name = field.get('name', '')
            if field_name in reverse_mapping:
                mapped_field = field.copy()
                mapped_field['name'] = reverse_mapping[field_name]
                mapped_field['original_name'] = field_name
                mapped_fields.append(mapped_field)
            else:
                mapped_fields.append(field.copy())
        data_info['mapped_fields'] = mapped_fields
        app.logger.info(f"[CONFIGURE_FIELDS] mapped_fields: {[f.get('name') for f in mapped_fields]}")

        # 映射预览数据
        preview = data_info.get('preview', [])
        if preview:
            mapped_preview = []
            for row in preview:
                mapped_row = {}
                for key, value in row.items():
                    mapped_key = reverse_mapping.get(key, key)
                    mapped_row[mapped_key] = value
                mapped_preview.append(mapped_row)
            data_info['mapped_preview'] = mapped_preview
            app.logger.info(f"[CONFIGURE_FIELDS] mapped_preview[0] keys: {list(mapped_preview[0].keys()) if mapped_preview else 'EMPTY'}")

        session['data_info'] = data_info
        app.logger.info(f"[CONFIGURE_FIELDS] session data_info keys after: {list(session.get('data_info', {}).keys())}")

    # 存储科目余额表映射（如果有）
    if balance_field_mapping:
        session['balance_field_mapping'] = balance_field_mapping

        # 同样更新 balance_data_info
        balance_info = session.get('balance_data_info', {})
        if balance_info:
            rev_balance = {v: k for k, v in balance_field_mapping.items()}
            mapped_fields = []
            for field in balance_info.get('fields', []):
                fname = field.get('name', '')
                if fname in rev_balance:
                    mf = field.copy()
                    mf['name'] = rev_balance[fname]
                    mf['original_name'] = fname
                    mapped_fields.append(mf)
                else:
                    mapped_fields.append(field.copy())
            balance_info['mapped_fields'] = mapped_fields

            bpreview = balance_info.get('preview', [])
            if bpreview:
                mapped_preview = []
                for row in bpreview:
                    mrow = {}
                    for key, value in row.items():
                        mrow[rev_balance.get(key, key)] = value
                    mapped_preview.append(mrow)
                balance_info['mapped_preview'] = mapped_preview

            session['balance_data_info'] = balance_info

    has_balance = bool(session.get('balance_data_info'))

    # ---- 导入数据到 DuckDB ----
    import_success = False
    try:
        engine = get_duckdb_engine()
        filepath = session.get('filepath')
        field_mapping = session.get('field_mapping')
        upload_opts = session.get('upload_options', {})
        sheet_name = upload_opts.get('sheet_name')
        header_row = upload_opts.get('header_row')
        constant_cols = session.get('manual_fills') or None
        if filepath and field_mapping:
            ext = os.path.splitext(filepath)[1].lower()
            reverse_mapping = {v: k for k, v in field_mapping.items()}
            if ext == '.csv':
                rows = engine.import_csv(filepath, 'data', reverse_mapping, header_row=header_row,
                                         constant_columns=constant_cols)
            elif ext in ('.xls', '.xlsx'):
                rows = engine.import_xlsx(filepath, 'data', reverse_mapping,
                                          sheet_name=sheet_name, header_row=header_row,
                                          constant_columns=constant_cols)
            else:
                rows = 0
            app.logger.info(f"[DUCKDB] 序时账已导入: {filepath} → {rows} 行")
            if rows == 0:
                app.logger.warning(f"[DUCKDB] 序时账导入后行数为 0，请检查源文件")
            import_success = True
        else:
            app.logger.warning(f"[DUCKDB] 跳过序时账导入: filepath={filepath}, field_mapping={'有' if field_mapping else '无'}")

        balance_filepath = session.get('balance_filepath')
        balance_field_mapping = session.get('balance_field_mapping')
        balance_constant_cols = session.get('balance_manual_fills') or None
        balance_upload_opts = session.get('balance_upload_options', {})
        balance_sheet_name = balance_upload_opts.get('sheet_name')
        balance_header_row = balance_upload_opts.get('header_row')
        if balance_filepath and balance_field_mapping:
            ext = os.path.splitext(balance_filepath)[1].lower()
            rev_balance = {v: k for k, v in balance_field_mapping.items()}
            if ext == '.csv':
                engine.import_csv(balance_filepath, 'balance_data', rev_balance,
                                  header_row=balance_header_row,
                                  constant_columns=balance_constant_cols)
            elif ext in ('.xls', '.xlsx'):
                engine.import_xlsx(balance_filepath, 'balance_data', rev_balance,
                                   sheet_name=balance_sheet_name, header_row=balance_header_row,
                                   constant_columns=balance_constant_cols)
            app.logger.info(f"[DUCKDB] 科目余额表已导入: {balance_filepath}")
    except Exception as e:
        app.logger.error(f"[DUCKDB IMPORT ERROR] {str(e)}")
        # DuckDB 导入失败时清理残留的 .db 文件
        cleanup_session_db()
        return jsonify({
            'success': False,
            'error': f'数据导入DuckDB失败: {str(e)}，字段映射已保存，请检查源文件后重试'
        })

    session['duckdb_imported'] = import_success

    if not import_success:
        app.logger.warning("[DUCKDB] 序时账未导入（无文件或无字段映射），字段映射配置已保存")

    # 映射成功后自动保存历史记录
    if import_success:
        try:
            filepath = session.get('filepath')
            if filepath and os.path.exists(filepath):
                data_info = session.get('data_info', {})
                cols = [f.get('name', '') for f in data_info.get('fields', [])]
                balance_info = session.get('balance_data_info', {})
                balance_cols = [f.get('name', '') for f in balance_info.get('fields', [])]
                save_mapping(
                    filename=os.path.basename(filepath),
                    file_size=os.path.getsize(filepath),
                    field_mapping=field_mapping,
                    balance_field_mapping=balance_field_mapping or {},
                    original_columns=cols,
                    balance_original_columns=balance_cols,
                )
                app.logger.info(f"[HISTORY] 映射历史已保存: {os.path.basename(filepath)}")
        except Exception as e:
            app.logger.error(f"[HISTORY] 保存映射历史失败: {e}")

    return jsonify({
        'success': True,
        'message': '字段映射已保存并应用',
        'has_balance_data': has_balance
    })


@app.route('/api/auto-map-fields', methods=['POST'])
def auto_map_fields():
    """AI 自动字段映射 — 调用 AI 根据列名、类型、样本值推荐映射"""
    data = request.json
    api_key = session.get('api_key')

    if not api_key:
        return jsonify({'success': False, 'error': '请先配置 API Key'})

    journal_fields = data.get('journal_fields', [])
    journal_standard = data.get('journal_standard_fields', [])
    balance_fields = data.get('balance_fields', [])
    balance_standard = data.get('balance_standard_fields', [])

    if not journal_fields or not journal_standard:
        return jsonify({'success': False, 'error': '字段信息不完整'})

    try:
        provider = session.get('ai_provider', 'deepseek')
        model = session.get('ai_model')
        plain_key = crypto_decrypt(api_key, Config.SECRET_KEY)
        provider_config = Config.AI_PROVIDERS.get(provider, Config.AI_PROVIDERS["deepseek"])
        api_url = provider_config["api_url"]
        model_name = model or provider_config["model"]

        # Build prompt
        lines = [
            "你是一个数据工程师，负责将用户上传的Excel列映射到标准字段。",
            "根据列名、数据类型和样本值推断每列的含义，映射到最合适的标准字段。",
            "",
            "## 用户序时账列",
        ]
        for f in journal_fields:
            lines.append(f"- {f['name']} (类型: {f['type']}, 样本: {f.get('sample', 'N/A')})")

        lines.extend(["", "## 标准字段（序时账）"])
        for f in journal_standard:
            lines.append(f"- {f['id']}: {f['name']} — {f['description']} (类型: {f['type']})")

        if balance_fields and balance_standard:
            lines.extend(["", "## 用户科目余额表列"])
            for f in balance_fields:
                lines.append(f"- {f['name']} (类型: {f['type']}, 样本: {f.get('sample', 'N/A')})")

            lines.extend(["", "## 标准字段（科目余额表）"])
            for f in balance_standard:
                lines.append(f"- {f['id']}: {f['name']} — {f['description']} (类型: {f['type']})")

        lines.extend([
            "",
            "返回纯 JSON，不要 Markdown 包裹。格式：",
            '{ "journal_mapping": { "date": "用户列名", ... }, "balance_mapping": { ... } }',
            "映射不确认的字段就省略，balance_mapping 无数据时返回 {}。",
        ])
        prompt = "\n".join(lines)

        # Call AI
        import requests as http_req
        headers = {
            "Authorization": f"Bearer {plain_key}",
            "Content-Type": "application/json"
        }
        req_data = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "你只返回 JSON，不加 Markdown 代码块。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 2000,
        }
        resp = http_req.post(api_url, headers=headers, json=req_data, timeout=30)
        if resp.status_code != 200:
            return jsonify({'success': False, 'error': f'AI 请求失败: {resp.status_code}'})

        content = resp.json()['choices'][0]['message']['content'].strip()

        # Strip markdown code block wrappers if present
        if content.startswith('```'):
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            content = content.strip()

        # Find the first JSON object
        brace_start = content.find('{')
        brace_end = content.rfind('}')
        if brace_start >= 0 and brace_end >= 0:
            content = content[brace_start:brace_end + 1]

        mapping_result = json_module.loads(content)

        return jsonify({
            'success': True,
            'journal_mapping': mapping_result.get('journal_mapping', {}),
            'balance_mapping': mapping_result.get('balance_mapping', {})
        })

    except Exception as e:
        import traceback
        app.logger.error(f"[AUTO-MAP-FIELDS] {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'AI 自动映射失败: {str(e)}'})


@app.route('/api/mapping-history/check', methods=['GET'])
def check_mapping_history():
    """API: 检查当前上传文件是否有历史映射记录"""
    filepath = session.get('filepath')
    if not filepath or not os.path.exists(filepath):
        return jsonify({'has_match': False})

    try:
        data_info = session.get('data_info', {})
        cols = [f.get('name', '') for f in data_info.get('fields', [])]
        match = find_match(
            filename=os.path.basename(filepath),
            file_size=os.path.getsize(filepath),
            original_columns=cols,
        )
        if match:
            return jsonify({
                'has_match': True,
                'filename': match.get('filename', ''),
                'updated_at': match.get('updated_at', ''),
            })
    except Exception as e:
        app.logger.error(f"[HISTORY] 检查映射历史失败: {e}")

    return jsonify({'has_match': False})


@app.route('/api/mapping-history/apply', methods=['POST'])
def apply_mapping_history():
    """API: 应用历史映射到当前会话"""
    filepath = session.get('filepath')
    if not filepath or not os.path.exists(filepath):
        return jsonify({'success': False, 'error': '无上传文件'})

    try:
        data_info = session.get('data_info', {})
        cols = [f.get('name', '') for f in data_info.get('fields', [])]
        match = find_match(
            filename=os.path.basename(filepath),
            file_size=os.path.getsize(filepath),
            original_columns=cols,
        )
        if not match:
            return jsonify({'success': False, 'error': '未找到匹配的历史映射'})

        # 将历史映射写入 session
        session['field_mapping'] = match.get('field_mapping', {})
        session['mapping_prefilled'] = True

        balance_mapping = match.get('balance_field_mapping', {})
        if balance_mapping:
            session['balance_field_mapping'] = balance_mapping

        app.logger.info(f"[HISTORY] 已应用历史映射: {match.get('filename')}")
        return jsonify({'success': True})

    except Exception as e:
        app.logger.error(f"[HISTORY] 应用映射历史失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api-config', methods=['GET'])
def api_config_page():
    """API配置页面"""
    if 'data_info' not in session:
        return redirect(url_for('upload_page'))
    return render_template('api-config.html')

@app.route('/query', methods=['GET'])
def query_page():
    """查询页面"""
    if 'data_info' not in session:
        return redirect(url_for('upload_page'))

    # 传递数据信息到模板
    data_info = session.get('data_info', {})
    return render_template('query.html', data_info=data_info)

# 注释掉results页面，因为查询页面已经包含完整的结果展示功能
# @app.route('/results', methods=['GET'])
# def results_page():
#     """结果页面"""
#     if 'data_info' not in session:
#         return redirect(url_for('upload_page'))
#     return render_template('results.html')

@app.route('/api/upload/preview', methods=['POST'])
def upload_file_preview():
    """API: 上传文件并预览结构（检测 sheet 和原始行），不进行数据解析"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '没有选择文件'})

    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': '没有选择文件'})

    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': '不支持的文件类型'})

    # 清理旧的临时文件
    old_pending = session.pop('pending_filepath', None)
    if old_pending and os.path.exists(old_pending):
        try:
            os.remove(old_pending)
        except Exception:
            pass

    # 保存文件到临时路径
    temp_filename = f"temp_{int(time.time())}_{file.filename}"
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_filename)
    file.save(temp_path)

    ext = os.path.splitext(file.filename)[1].lower()
    is_excel = ext in ('.xlsx', '.xls')

    try:
        sheets = {}
        sheet_names = []

        if is_excel:
            # 检测 sheet 名称
            sheet_names = DataProcessor.get_xlsx_sheet_names(temp_path)
            # 获取原始预览
            raw = DataProcessor.preview_raw(temp_path, nrows=15)
            for name in sheet_names:
                info = raw.get(name, {})
                sheets[name] = {
                    'total_rows': info.get('total_rows', 0),
                    'total_cols': info.get('total_cols', 0),
                    'preview_rows': info.get('rows', []),
                }
        else:
            # CSV 当作单 sheet
            raw = DataProcessor.preview_raw(temp_path, nrows=15)
            csv_info = raw.get('__csv__', {})
            sheet_names = ['__csv__']
            sheets['__csv__'] = {
                'total_rows': csv_info.get('total_rows', 0),
                'total_cols': csv_info.get('total_cols', 0),
                'preview_rows': csv_info.get('rows', []),
            }

        # 保存文件路径到 session 供后续解析使用
        session['pending_filepath'] = temp_path
        session['pending_filename'] = file.filename

        return jsonify({
            'success': True,
            'filename': file.filename,
            'file_type': 'excel' if is_excel else 'csv',
            'sheet_names': sheet_names,
            'sheets': sheets,
            'is_multi_sheet': len(sheet_names) > 1,
        })

    except Exception as e:
        import traceback
        app.logger.error(f"[UPLOAD PREVIEW ERROR] {str(e)}\n{traceback.format_exc()}")
        # 清理临时文件
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return jsonify({'success': False, 'error': f'文件预览失败: {str(e)}'})


@app.route('/api/upload', methods=['POST'])
def upload_file():
    """API: 处理文件上传（支持 sheet 选择和 header row 指定）"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '没有选择文件'})

    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': '没有选择文件'})

    # 检查文件扩展名
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': '不支持的文件类型'})

    # 清理旧的 DuckDB 数据（上传新文件前）
    cleanup_session_db()
    session.pop('data_info', None)
    session.pop('filepath', None)
    session.pop('field_mapping', None)
    session.pop('balance_field_mapping', None)

    # 保存文件
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(filepath)

    # 解析可选参数：sheet_name 和 header_row
    sheet_name = request.form.get('sheet_name') or None
    header_row_raw = request.form.get('header_row')
    header_row = int(header_row_raw) - 1 if header_row_raw and header_row_raw.isdigit() else None
    # header_row 在前端从 1 开始计数，转为 0-indexed 传给 pandas

    app.logger.info(f"[UPLOAD] sheet_name={sheet_name}, header_row={header_row}(前端输入={header_row_raw})")

    # 调用DataProcessor处理文件
    try:
        processor = DataProcessor(filepath)
        data_info = processor.process(
            sheet_name=sheet_name if sheet_name != '__csv__' else None,
            header_row=header_row,
        )
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"文件处理失败详情: {error_details}")
        # 清理上传失败的文件
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                app.logger.info(f"[CLEANUP] 已删除上传失败的文件: {filepath}")
            except Exception as cleanup_err:
                app.logger.error(f"[CLEANUP] 文件删除失败: {cleanup_err}")
        return jsonify({'success': False, 'error': f'文件处理失败: {str(e)}'})

    # 存储到会话
    session['filepath'] = filepath
    session['data_info'] = data_info
    session['upload_options'] = {'sheet_name': sheet_name, 'header_row': header_row}
    session['duckdb_imported'] = False

    return jsonify(data_info)

@app.route('/api/providers', methods=['GET'])
def get_providers():
    """API: 返回所有AI供应商列表"""
    providers = []
    for pid, cfg in Config.AI_PROVIDERS.items():
        info = {
            'id': pid,
            'name': cfg['name'],
            'model': cfg['model'],
            'doc_url': cfg['doc_url'],
            'pre_configured': cfg.get('pre_configured', False),
        }
        providers.append(info)
    return jsonify({'success': True, 'providers': providers})


@app.route('/api/configure-api', methods=['POST'])
def configure_api():
    """API: 配置AI API Key（支持DeepSeek/百炼/Kimi，自动加密存储）"""
    data = request.json
    api_key = data.get('api_key', '')
    provider = data.get('provider', 'deepseek')
    model = data.get('model')

    # 验证供应商ID
    if provider not in Config.AI_PROVIDERS:
        return jsonify({'success': False, 'error': f'不支持的AI供应商: {provider}'})

    provider_cfg = Config.AI_PROVIDERS[provider]

    # 百炼预置密钥：用户不填 key 时自动使用加密存储的内置 key
    if not api_key and provider_cfg.get('pre_configured') and provider_cfg.get('encrypted_key'):
        # 内置 Key：解密后再加密存储，保持统一格式
        plain_key = crypto_decrypt(provider_cfg['encrypted_key'], Config.SECRET_KEY)
        api_key = crypto_encrypt(plain_key, Config.SECRET_KEY)
        session['api_key_source'] = 'builtin'
    elif not api_key:
        return jsonify({'success': False, 'error': 'API Key不能为空'})
    else:
        # 用户手动输入的 key → 加密后存储
        api_key = crypto_encrypt(api_key, Config.SECRET_KEY)
        session['api_key_source'] = 'user'

    # 存储到会话（始终加密存储）
    session['api_key'] = api_key
    session['ai_provider'] = provider
    if model:
        session['ai_model'] = model

    # 复核模型配置（可选）
    if 'review_api_key' in data:
        rk = data['review_api_key']
        if rk:
            session['review_api_key'] = crypto_encrypt(rk, Config.SECRET_KEY)
        else:
            session.pop('review_api_key', None)
    if 'review_provider' in data:
        rp = data['review_provider']
        session['review_provider'] = rp if rp else None
    if 'review_model' in data:
        rm = data['review_model']
        session['review_model'] = rm if rm else None
    if 'review_api_url' in data:
        ru = data['review_api_url']
        session['review_api_url'] = ru if ru else None

    has_balance = bool(session.get('balance_data_info'))

    return jsonify({
        'success': True,
        'message': 'API Key已保存',
        'has_balance_data': has_balance,
        'pre_configured': session.get('api_key_source') == 'builtin',
    })

@app.route('/api/review-code', methods=['POST'])
def review_code():
    """API: 复核 AI 生成的 SQL 代码 — 由第二 AI 模型（或同级模型）从语法、安全、意图、性能四个维度审查"""
    data = request.json
    code = data.get('code', '')
    query = data.get('query', '')

    if not code:
        return jsonify({'success': False, 'error': '代码不能为空'})

    api_key = session.get('review_api_key') or session.get('api_key')
    if not api_key:
        return jsonify({'success': False, 'error': '请先配置 API Key（主模型或复核模型）'})

    try:
        provider = session.get('review_provider') or session.get('ai_provider', 'deepseek')
        model = session.get('review_model') or session.get('ai_model')
        review_api_url = session.get('review_api_url')

        plain_key = crypto_decrypt(api_key, Config.SECRET_KEY)
        provider_config = Config.AI_PROVIDERS.get(provider, Config.AI_PROVIDERS["deepseek"])
        api_url = review_api_url or provider_config["api_url"]
        model_name = model or provider_config["model"]

        # 获取字段信息用于上下文
        data_info = session.get('data_info', {})
        fields = data_info.get('mapped_fields', data_info.get('fields', []))
        fields_desc = "\n".join([f"- {f['name']} ({f['type']})" for f in fields[:20]])

        prompt = f"""你是一名资深的财务数据 SQL 审查专家。请从以下四个维度审查 AI 生成的 DuckDB SQL 代码。

## 用户查询
{query}

## 生成的 SQL 代码
```sql
{code}
```

## 数据表字段
{fields_desc or '（无详细字段信息）'}

## 审查维度
1. **语法检查** — 是否符合 DuckDB SQL 语法？
2. **安全审查** — 是否仅包含 SELECT 只读操作？有无危险语句？
3. **意图匹配** — SQL 逻辑是否准确反映了用户的查询需求？
4. **性能优化** — 是否有明显的性能问题？能否优化？

## 输出格式
请输出以下 JSON 格式，注意必须是合法的 JSON，不要包含 Markdown 代码块包裹：
{{
  "passed": true/false,
  "summary": "一句话总结审查结论",
  "aspects": [
    {{"name": "语法检查", "passed": true/false, "reason": "详细说明"}},
    {{"name": "安全审查", "passed": true/false, "reason": "详细说明"}},
    {{"name": "意图匹配", "passed": true/false, "reason": "详细说明"}},
    {{"name": "性能优化", "passed": true/false, "reason": "详细说明"}}
  ]
}}"""

        import requests as http_req
        headers = {
            "Authorization": f"Bearer {plain_key}",
            "Content-Type": "application/json",
        }
        req_data = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "你是一名资深的 SQL 审查专家。只输出 JSON，不要加 Markdown 代码块包裹。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 1500,
        }
        resp = http_req.post(api_url, headers=headers, json=req_data, timeout=60)
        if resp.status_code != 200:
            return jsonify({'success': False, 'error': f'复核请求失败: {resp.status_code}'})

        content = resp.json()['choices'][0]['message']['content'].strip()

        # 清理 Markdown 包裹
        if content.startswith('```'):
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            content = content.strip()

        # 提取 JSON 对象
        brace_start = content.find('{')
        brace_end = content.rfind('}')
        if brace_start >= 0 and brace_end >= 0:
            content = content[brace_start:brace_end + 1]

        review_result = json_module.loads(content)

        return jsonify({
            'success': True,
            'review': review_result,
            'model_used': model_name,
        })

    except Exception as e:
        import traceback
        app.logger.error(f"[REVIEW-CODE] {str(e)}\n{traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': f'代码复核失败: {str(e)}',
        })


@app.route('/api/generate-code', methods=['POST'])
def generate_code():
    """API: 生成SQL查询"""
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'success': False, 'error': '查询语句不能为空'})

    api_key = session.get('api_key')
    if not api_key:
        return jsonify({'success': False, 'error': '请先配置API Key'})

    data_info = session.get('data_info')
    if not data_info:
        return jsonify({'success': False, 'error': '请先上传数据文件'})

    try:
        provider = session.get('ai_provider', 'deepseek')
        model = session.get('ai_model')
        # 解密存储的 API Key
        plain_key = crypto_decrypt(api_key, Config.SECRET_KEY)
        generator = AICodeGenerator(plain_key, provider=provider, model=model)
        fields = data_info.get('mapped_fields', data_info.get('fields', []))
        preview = data_info.get('mapped_preview', data_info.get('preview', []))

        # 如果已导入 DuckDB，使用数据库 schema 信息
        if session.get('duckdb_imported'):
            engine = get_duckdb_engine()
            fields = engine.get_schema('data')
            app.logger.info(f"[GENERATE_CODE] Using DuckDB schema: {fields}")

        app.logger.info(f"[GENERATE_CODE] data_info keys: {list(data_info.keys())}")
        sql = generator.generate(query, fields, preview)
        log_generate(
            session_id=session.get('session_id', ''),
            user_query=query,
            generated_sql=sql,
            success=True,
        )
        # 保存查询历史到 session
        history = session.get('query_history', [])
        history.append({
            'query': query,
            'sql': sql,
            'timestamp': time.strftime('%H:%M:%S'),
            'success': True,
        })
        session['query_history'] = history[-50:]  # 最多保留 50 条
        # 保存当前查询信息供导出使用
        session['last_query_info'] = {
            'query_text': query,
            'sql_code': sql,
        }
        # 自动生成代码解释供导出使用
        try:
            session['last_explanation'] = generator.explain_code(sql)
        except Exception:
            session['last_explanation'] = ''
        return jsonify({'success': True, 'code': sql})
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        app.logger.error(f"[GENERATE_CODE ERROR] {str(e)}\n{tb}")
        log_generate(
            session_id=session.get('session_id', ''),
            user_query=query,
            generated_sql='',
            success=False,
            error=str(e),
        )
        history = session.get('query_history', [])
        history.append({
            'query': query,
            'sql': '',
            'timestamp': time.strftime('%H:%M:%S'),
            'success': False,
        })
        session['query_history'] = history[-50:]
        return jsonify({'success': False, 'error': f'SQL生成失败: {str(e)}'})


@app.route('/api/query-history', methods=['GET'])
def query_history():
    """API: 返回当前会话的查询历史"""
    history = session.get('query_history', [])
    return jsonify({'success': True, 'history': history})


@app.route('/api/optimize-query', methods=['POST'])
def optimize_query():
    """API: 优化自然语言查询（本地词典 + AI 同义词扩展）"""
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'success': False, 'error': '查询语句不能为空'})

    # 1. 本地词典初步扩展
    from modules.synonym_dict import expand_keywords, find_keywords
    local_expanded = expand_keywords(query)
    expanded_terms = [m['standard'] for m in find_keywords(query)]

    # 2. AI 二次扩展
    api_key = session.get('api_key')
    if not api_key:
        # 无 API Key 时返回本地扩展结果
        return jsonify({
            'success': True,
            'original_query': query,
            'local_expanded': local_expanded,
            'optimized_query': local_expanded,
            'expanded_terms': expanded_terms,
            'source': 'local'
        })

    try:
        provider = session.get('ai_provider', 'deepseek')
        model = session.get('ai_model')
        plain_key = crypto_decrypt(api_key, Config.SECRET_KEY)
        generator = AICodeGenerator(plain_key, provider=provider, model=model)
        ai_optimized = generator.optimize_query(query, local_expanded=local_expanded)
        return jsonify({
            'success': True,
            'original_query': query,
            'local_expanded': local_expanded,
            'optimized_query': ai_optimized,
            'expanded_terms': expanded_terms,
            'source': 'ai'
        })
    except Exception as e:
        # AI 失败时降级到本地扩展
        return jsonify({
            'success': True,
            'original_query': query,
            'local_expanded': local_expanded,
            'optimized_query': local_expanded,
            'expanded_terms': expanded_terms,
            'source': 'local',
            'warning': f'AI 优化失败，已使用本地词典扩展: {str(e)}'
        })


@app.route('/api/explain-code', methods=['POST'])
def explain_code():
    """API: 解释代码功能"""
    data = request.json
    code = data.get('code')

    if not code:
        return jsonify({'success': False, 'error': '代码不能为空'})

    api_key = session.get('api_key')
    if not api_key:
        return jsonify({'success': False, 'error': '请先配置API Key'})

    try:
        provider = session.get('ai_provider', 'deepseek')
        model = session.get('ai_model')
        plain_key = crypto_decrypt(api_key, Config.SECRET_KEY)
        generator = AICodeGenerator(plain_key, provider=provider, model=model)
        explanation = generator.explain_code(code)
        session['last_explanation'] = explanation
        return jsonify({'success': True, 'explanation': explanation})
    except Exception as e:
        session['last_explanation'] = ''
        return jsonify({'success': False, 'error': f'代码解释失败: {str(e)}'})


@app.route('/api/preset-rules', methods=['GET'])
def preset_rules_list():
    """API: 返回所有预设筛选规则（扁平列表）"""
    rules = get_rules()
    return jsonify({'success': True, 'rules': rules})


@app.route('/api/preset-rules/packs', methods=['GET'])
def preset_rules_packs():
    """API: 返回规则包分组结构（含内置包 + 自定义规则）"""
    packs = get_packs()
    custom_rules = get_custom_rules()
    return jsonify({
        'success': True,
        'packs': packs,
        'custom_rules': custom_rules,
    })


@app.route('/api/preset-rules', methods=['POST'])
def preset_rules_save():
    """API: 保存自定义规则（新建或更新）"""
    data = request.json
    if not data:
        return jsonify({'success': False, 'error': '请求数据不能为空'})
    if not data.get('name') or not data.get('sql_template'):
        return jsonify({'success': False, 'error': '规则名称和 SQL 模板不能为空'})
    rule = save_rule(data)
    return jsonify({'success': True, 'rule': rule})


@app.route('/api/preset-rules/<rule_id>', methods=['DELETE'])
def preset_rules_delete(rule_id):
    """API: 删除自定义规则"""
    ok = delete_rule(rule_id)
    if ok:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': '仅允许删除自定义规则，或规则不存在'})


@app.route('/api/preset-rules/apply', methods=['POST'])
def preset_rules_apply():
    """API: 应用预设规则，返回生成的 SQL"""
    data = request.json
    rule_id = data.get('rule_id')
    params = data.get('params', {})
    if not rule_id:
        return jsonify({'success': False, 'error': 'rule_id 不能为空'})
    rule = get_rule_by_id(rule_id)
    if not rule:
        return jsonify({'success': False, 'error': f'未找到规则: {rule_id}'})
    sql = apply_rule(rule_id, params)
    if sql is None:
        return jsonify({'success': False, 'error': '规则应用失败，请检查参数'})
    return jsonify({
        'success': True,
        'sql': sql,
        'rule': {'id': rule['id'], 'name': rule['name'], 'category': rule['category']}
    })


@app.route('/api/sampling/methods', methods=['GET'])
def sampling_methods():
    """API: 返回所有取样方法"""
    return jsonify({'success': True, 'methods': get_methods()})


@app.route('/api/sampling/execute', methods=['POST'])
def sampling_execute():
    """API: 执行取样，返回结果"""
    data = request.json
    method_id = data.get('method_id')
    params = data.get('params', {})

    if not method_id:
        return jsonify({'success': False, 'error': 'method_id 不能为空'})

    methods = get_methods()
    method = next((m for m in methods if m['id'] == method_id), None)
    if not method:
        return jsonify({'success': False, 'error': f'未找到取样方法: {method_id}'})

    sql = generate_sql(method_id, params)
    if sql is None:
        return jsonify({'success': False, 'error': '无法生成取样 SQL'})

    engine = get_duckdb_engine()
    if not engine.table_exists('data'):
        return jsonify({'success': False, 'error': '数据尚未导入，请先完成字段映射'})

    result = engine.execute(sql)
    if result.get('success'):
        return jsonify({
            'success': True,
            'method': method['name'],
            'result': result.get('result', {}),
            'sql': sql.strip()
        })
    else:
        return jsonify({'success': False, 'error': f'取样执行失败: {result.get("error")}'})


@app.route('/api/execute', methods=['POST'])
def execute_code():
    """API: 执行 SQL 查询"""
    data = request.json
    sql = data.get('code')

    if not sql:
        return jsonify({'success': False, 'error': 'SQL不能为空'})

    engine = get_duckdb_engine()

    # 优先通过 session 标记快速判断，标记丢失时检查实际的数据库状态
    if not session.get('duckdb_imported'):
        if not engine.table_exists('data'):
            # 表不存在，尝试重新导入
            filepath = session.get('filepath')
            field_mapping = session.get('field_mapping')
            upload_opts = session.get('upload_options', {})
            sheet_name = upload_opts.get('sheet_name')
            header_row = upload_opts.get('header_row')
            constant_cols = session.get('manual_fills') or None
            if filepath and field_mapping:
                try:
                    ext = os.path.splitext(filepath)[1].lower()
                    reverse_mapping = {v: k for k, v in field_mapping.items()}
                    if ext == '.csv':
                        engine.import_csv(filepath, 'data', reverse_mapping, header_row=header_row,
                                          constant_columns=constant_cols)
                    elif ext in ('.xls', '.xlsx'):
                        engine.import_xlsx(filepath, 'data', reverse_mapping,
                                           sheet_name=sheet_name, header_row=header_row,
                                           constant_columns=constant_cols)
                    else:
                        return jsonify({'success': False, 'error': '不支持的文件格式，请重新上传'})
                    session['duckdb_imported'] = True
                    app.logger.info(f"[DUCKDB] 执行查询前自动重导入成功: {filepath}")
                except Exception as e:
                    app.logger.error(f"[DUCKDB] 执行查询前重导入失败: {e}")
                    return jsonify({'success': False, 'error': f'数据尚未导入DuckDB，请先配置字段映射'})
            else:
                return jsonify({'success': False, 'error': '数据尚未导入DuckDB，请先配置字段映射'})
        else:
            # 表存在但标记丢失（如调试重启），修复标记
            session['duckdb_imported'] = True

    try:
        result = engine.execute(sql)

        # 审计日志
        row_count = None
        if result.get('success') and result.get('result', {}).get('type') == 'dataframe':
            row_count = len(result['result'].get('data', []))
        log_execute(
            session_id=session.get('session_id', ''),
            sql=sql,
            success=result.get('success', False),
            row_count=row_count,
            execution_time=result.get('execution_time'),
            error=None if result.get('success') else result.get('error'),
        )

        session['last_execution_result'] = {
            'success': result.get('success', False),
            'simplified_result': result.get('result', {})
        }
        # 保存实际执行的 SQL（可能被用户编辑过）
        info = session.get('last_query_info', {'query_text': '', 'sql_code': ''})
        info['sql_code'] = sql
        session['last_query_info'] = info

        return jsonify(result)
    except Exception as e:
        import traceback
        app.logger.error(f"[DUCKDB EXECUTE ERROR] {str(e)}\n{traceback.format_exc()}")
        log_execute(
            session_id=session.get('session_id', ''),
            sql=sql,
            success=False,
            error=str(e),
        )
        return jsonify({'success': False, 'error': f'SQL执行失败: {str(e)}'})

@app.route('/api/export', methods=['POST'])
def export_data():
    """API: 导出数据"""
    data = request.json
    format_type = data.get('format', 'csv')

    # 获取上次执行结果
    execution_result = session.get('last_execution_result')

    if not execution_result or not execution_result.get('success'):
        return jsonify({'success': False, 'error': '没有可导出的执行结果，请先执行查询'})

    # 检查是否有存储在临时文件中的完整结果
    result_data = None
    simplified_result = execution_result.get('simplified_result')
    if simplified_result and simplified_result.get('result_file'):
        # 从临时文件加载完整结果
        result_filename = simplified_result['result_file']
        result_filepath = os.path.join(app.config['UPLOAD_FOLDER'], result_filename)
        if os.path.exists(result_filepath):
            try:
                import json as json_module
                with open(result_filepath, 'r', encoding='utf-8') as f:
                    result_data = json_module.load(f)
            except Exception as e:
                app.logger.error(f"加载结果文件失败: {e}")
                # 继续尝试使用简化结果
                pass

    # 如果没有临时文件，尝试从会话中的结果获取
    if result_data is None:
        result_data = execution_result.get('result')
    if result_data is None:
        result_data = execution_result.get('simplified_result')
    if not result_data:
        return jsonify({'success': False, 'error': '执行结果为空，无法导出'})

    try:
        import pandas as pd

        # 根据结果类型创建DataFrame
        df = None
        result_type = result_data.get('type')

        if result_type == 'dataframe':
            # 处理DataFrame类型结果
            columns = result_data.get('columns', [])
            data_list = result_data.get('data', [])
            if data_list and columns:
                df = pd.DataFrame(data_list, columns=columns)
        elif result_type == 'list' or result_type == 'tuple':
            # 处理列表/元组类型结果
            values = result_data.get('values', [])
            if values:
                # 如果列表元素是字典，可以尝试转换为DataFrame
                if values and isinstance(values[0], dict):
                    df = pd.DataFrame(values)
                else:
                    df = pd.DataFrame({'值': values})
        elif result_type == 'dict':
            # 处理字典类型结果
            dict_data = result_data.get('data', {})
            if dict_data:
                # 将字典转换为DataFrame
                df = pd.DataFrame([dict_data])
        elif result_type == 'scalar':
            # 处理标量类型结果
            value = result_data.get('value')
            df = pd.DataFrame({'结果': [value]})
        else:
            return jsonify({'success': False, 'error': f'不支持的结果类型: {result_type}'})

        if df is None or len(df) == 0:
            return jsonify({'success': False, 'error': '没有可导出的数据'})

        # 生成文件名
        import time
        timestamp = int(time.time())
        filename = f'export_{timestamp}.{format_type}'
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # 导出文件
        if format_type == 'csv':
            df.to_csv(filepath, index=False, encoding='utf-8-sig')
        else:  # xlsx
            query_info = session.get('last_query_info', {})
            explanation = session.get('last_explanation', '')
            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                # Sheet 1: 查询信息
                info_rows = []
                info_rows.append({'项目': '自然语言查询', '内容': query_info.get('query_text', '')})
                info_rows.append({'项目': 'SQL代码', '内容': query_info.get('sql_code', '')})
                info_rows.append({'项目': '代码解释', '内容': explanation})
                info_df = pd.DataFrame(info_rows)
                info_df.to_excel(writer, sheet_name='查询信息', index=False)
                ws = writer.sheets['查询信息']
                ws.column_dimensions['A'].width = 14
                ws.column_dimensions['B'].width = 90
                from openpyxl.styles import Font, Alignment, PatternFill
                header_font = Font(bold=True, color='FFFFFF', size=11)
                header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
                for cell in ws[1]:
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=2, max_col=2):
                    for cell in row:
                        cell.alignment = Alignment(wrap_text=True, vertical='top')
                ws.row_dimensions[2].height = 40
                ws.row_dimensions[3].height = 120
                ws.row_dimensions[4].height = 200
                # Sheet 2: 查询结果
                df.to_excel(writer, sheet_name='查询结果', index=False)

        return send_file(filepath, as_attachment=True, download_name=filename)

    except Exception as e:
        return jsonify({'success': False, 'error': f'导出失败: {str(e)}'})


@app.route('/api/debug/duckdb-info', methods=['GET'])
def debug_duckdb_info():
    """调试: 查看 DuckDB 表状态"""
    try:
        engine = get_duckdb_engine()
        info = {'session_id': session.get('session_id'), 'duckdb_imported': session.get('duckdb_imported')}
        for tbl in ['data', 'balance_data']:
            if engine.table_exists(tbl):
                cols = engine.get_schema(tbl)
                cnt = engine.get_total_rows(tbl)
                info[tbl] = {'exists': True, 'columns': cols, 'row_count': cnt}
            else:
                info[tbl] = {'exists': False}
        return jsonify({'success': True, 'info': info})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS


def cleanup_stale_files():
    """启动时清理超过24小时的临时文件"""
    now = time.time()
    cutoff = 24 * 3600
    deleted = []

    # 清理 temp/db/*.db 和 *.wal
    db_dir = app.config['DUCKDB_DIR']
    if os.path.isdir(db_dir):
        for fname in os.listdir(db_dir):
            fpath = os.path.join(db_dir, fname)
            if not os.path.isfile(fpath):
                continue
            if fname.endswith('.db') or fname.endswith('.wal'):
                if now - os.path.getmtime(fpath) > cutoff:
                    try:
                        os.remove(fpath)
                        deleted.append(fpath)
                    except Exception as e:
                        app.logger.error(f"[CLEANUP STARTUP] 删除失败: {fpath}, {e}")

    # 清理 temp/result_*.json 和 temp/export_*.*
    upload_dir = app.config['UPLOAD_FOLDER']
    if os.path.isdir(upload_dir):
        for fname in os.listdir(upload_dir):
            fpath = os.path.join(upload_dir, fname)
            if not os.path.isfile(fpath):
                continue
            if not (fname.startswith('result_') or fname.startswith('export_')):
                continue
            if now - os.path.getmtime(fpath) > cutoff:
                try:
                    os.remove(fpath)
                    deleted.append(fpath)
                except Exception as e:
                    app.logger.error(f"[CLEANUP STARTUP] 删除失败: {fpath}, {e}")

    if deleted:
        app.logger.info(f"[CLEANUP STARTUP] 共清理 {len(deleted)} 个过期文件")
        for p in deleted:
            app.logger.info(f"[CLEANUP STARTUP]   已删除: {p}")
    else:
        app.logger.info("[CLEANUP STARTUP] 无需清理（无过期文件）")


if __name__ == '__main__':
    cleanup_stale_files()
    app.run(debug=True, port=5003)