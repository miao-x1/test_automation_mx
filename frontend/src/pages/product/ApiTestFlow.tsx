import { useState } from 'react';
import { Button, Input, Upload, message } from 'antd';
import { importFromSwagger } from '@/services/apiCase';
import { getExecutionStatus, runExecution } from '@/services/apiExec';
import { unwrap } from './helpers';
import TestResultView from './TestResultView';
import './product.css';

type Phase = 'form' | 'running' | 'failed' | 'done';

function stamp(text: string) {
  return `${new Date().toLocaleTimeString()}  ${text}`;
}

export default function ApiTestFlow({ onBack }: { onBack: () => void }) {
  const [baseUrl, setBaseUrl] = useState('');
  const [swaggerText, setSwaggerText] = useState('');
  const [fileName, setFileName] = useState('');
  const [phase, setPhase] = useState<Phase>('form');
  const [logs, setLogs] = useState<string[]>([]);
  const [imported, setImported] = useState<{ id: number; title: string }[]>([]);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const readFile = async (file: File) => {
    const text = await file.text();
    setSwaggerText(text);
    setFileName(file.name);
    message.success('已读取接口文档');
    return false;
  };

  const start = async () => {
    if (!swaggerText.trim()) {
      message.warning('请上传或粘贴 Swagger / OpenAPI JSON');
      return;
    }
    let swagger: Record<string, unknown>;
    try {
      swagger = JSON.parse(swaggerText);
    } catch {
      message.error('不是合法 JSON，当前版本只支持 OpenAPI/Swagger JSON');
      return;
    }
    if (!swagger.paths && !swagger.openapi && !swagger.swagger) {
      message.error('当前文件不像 OpenAPI/Swagger。Postman Collection 请先转成 OpenAPI。');
      return;
    }
    setBusy(true);
    setPhase('running');
    setError('');
    setLogs([stamp('开始解析接口文档')]);
    try {
      const importedRes: any = unwrap(await importFromSwagger({
        swagger_json: swagger,
        base_url: baseUrl || undefined,
      }));
      const cases = importedRes?.case_ids || [];
      setImported(cases);
      setLogs((prev) => [...prev, stamp(`已导入 ${importedRes?.imported_count ?? cases.length} 个接口用例`)]);
      if (!cases.length) {
        throw new Error(importedRes?.imported_count === 0 ? '这些接口之前已经导入过，没有新的可执行用例' : '没有解析到可执行接口');
      }
      setLogs((prev) => [...prev, stamp('开始执行接口')]);
      const runRes: any = unwrap(await runExecution({
        case_ids: cases.map((item: any) => item.id),
        base_url: baseUrl || undefined,
      }));
      const executionId = runRes?.execution_id;
      if (!executionId) throw new Error('未能提交接口执行');
      let status: any = null;
      for (let i = 0; i < 60; i += 1) {
        status = unwrap(await getExecutionStatus(executionId));
        setLogs((prev) => [...prev, stamp(`执行状态：${status?.status || '查询中'}`)]);
        if (!['queued', 'pending', 'running', 'waiting'].includes(String(status?.status || ''))) break;
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      if (!status || ['queued', 'pending', 'running', 'waiting'].includes(String(status.status || ''))) {
        throw new Error('接口测试没有在时限内结束');
      }
      setResult({ ...status, success_count: status.success_count || status.analysis?.passed, failed_count: status.failed_count || status.analysis?.failed });
      setPhase('done');
    } catch (err: any) {
      const text = err?.response?.data?.detail || err?.message || '接口测试失败';
      setError(text);
      message.error(text);
      setPhase('failed');
    } finally {
      setBusy(false);
    }
  };

  if (phase === 'done' && result) {
    return <TestResultView result={result} cases={imported} executionId={result.execution_id} onRetest={() => setPhase('form')} onBack={onBack} />;
  }

  if (phase === 'running' || phase === 'failed') {
    return (
      <div>
        <div className="product-hero">
          <h1>{phase === 'failed' ? '接口测试未完成' : '正在执行接口测试'}</h1>
          <p>解析接口 → 生成用例 → 执行请求 → 分析返回</p>
        </div>
        <div className="product-card">
          <pre className="product-log">{logs.join('\n') || '等待日志'}</pre>
          {error && <p className="product-fail">{error}</p>}
          <div className="product-cta">
            <Button onClick={() => setPhase('form')} disabled={busy}>返回修改</Button>
            {phase === 'failed' && <Button type="primary" onClick={start} disabled={busy} style={{ marginLeft: 12 }}>重试</Button>}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="product-hero">
        <p><button type="button" className="product-text-btn" onClick={onBack}>测试中心</button> / API 接口测试</p>
        <h1>创建接口测试</h1>
        <p>上传 Swagger / OpenAPI，系统会解析接口、生成用例并真实发请求。这不是 Web 页面测试。</p>
      </div>
      <div className="product-card">
        <label className="product-label">接口基础地址</label>
        <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com" />
      </div>
      <div className="product-card">
        <label className="product-label">Swagger / OpenAPI</label>
        <Upload.Dragger accept=".json,application/json" maxCount={1} showUploadList={false} beforeUpload={readFile}>
          <p>{fileName || '上传 swagger.json / openapi.json'}</p>
        </Upload.Dragger>
        <Input.TextArea
          style={{ marginTop: 12 }}
          value={swaggerText}
          onChange={(e) => setSwaggerText(e.target.value)}
          placeholder="也可以直接粘贴 OpenAPI JSON"
          autoSize={{ minRows: 8, maxRows: 16 }}
        />
        <p className="product-note">只支持 Swagger/OpenAPI JSON。不支持 Postman Collection。</p>
        <div className="product-cta">
          <Button onClick={onBack}>返回测试中心</Button>
          <Button type="primary" size="large" loading={busy} onClick={start} style={{ marginLeft: 12 }}>开始接口测试</Button>
        </div>
      </div>
    </div>
  );
}
