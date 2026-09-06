import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button, Input, Upload, message } from 'antd';
import request from '@/services/request';
import { FileTextOutlined, PictureOutlined } from '@ant-design/icons';
import { browserApiUrl } from '@/utils/apiUrl';
import { assertUploadAllowed, formatUploadError } from '@/utils/uploadGuard';
import { WEB_MODES, buildWebRequirement, type WebModeId } from './testModes';
import { isPageUrl, unwrap, type UserStep } from './helpers';
import { runAnalyzePipeline } from './runWebPipeline';
import TestRunPanel from './TestRunPanel';
import TestResultView from './TestResultView';
import './product.css';

type Phase = 'form' | 'running' | 'failed' | 'done';

export default function WebTestFlow({ onBack }: { onBack: () => void }) {
  const [params] = useSearchParams();
  const [url, setUrl] = useState('');
  const [requirement, setRequirement] = useState('');
  const [modeId, setModeId] = useState<WebModeId>('explore');
  const [imagePath, setImagePath] = useState('');
  const [imagePreview, setImagePreview] = useState('');
  const [documentPath, setDocumentPath] = useState('');
  const [documentName, setDocumentName] = useState('');
  const [phase, setPhase] = useState<Phase>('form');
  const [steps, setSteps] = useState<UserStep[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [cases, setCases] = useState<any[]>([]);
  const [executionId, setExecutionId] = useState<number | null>(null);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const mode = WEB_MODES.find((item) => item.id === modeId) || WEB_MODES[0];

  useEffect(() => {
    const rerunId = params.get('rerun');
    if (rerunId) {
      request.get(`/requirement/${rerunId}`).then((res: any) => {
        const detail = unwrap(res);
        const page = (detail?.requirement || '').match(/https?:\/\/[^\s，。]+/)?.[0] || '';
        setUrl(page);
        setRequirement(detail?.requirement || '');
      }).catch(() => message.error('无法载入上次测试内容'));
      return;
    }
    const saved = sessionStorage.getItem('web_test_draft');
    if (!saved) return;
    try {
      const draft = JSON.parse(saved);
      setUrl(draft.url || '');
      setRequirement(draft.requirement || '');
    } catch { /* ignore */ }
  }, [params]);

  const uploadImage = async (file: File) => {
    try {
      await assertUploadAllowed(file, 'image');
      const reader = new FileReader();
      reader.onload = (e) => setImagePreview(String(e.target?.result || ''));
      reader.readAsDataURL(file);
      const formData = new FormData();
      formData.append('files', file);
      const res = await fetch(browserApiUrl('/requirement/upload_images'), { method: 'POST', body: formData, credentials: 'include' });
      const data = await res.json();
      const path = data?.data?.image_paths?.[0];
      if (!res.ok || !path) throw new Error(data?.detail || data?.message || '图片上传失败');
      setImagePath(path);
      message.success('页面截图已上传');
    } catch (err) {
      setImagePath('');
      setImagePreview('');
      message.error(formatUploadError(err));
    }
    return false;
  };

  const uploadDocument = async (file: File) => {
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch(browserApiUrl('/requirement/upload_document'), { method: 'POST', body: formData, credentials: 'include' });
      const data = await res.json();
      const path = data?.data?.document_path;
      if (!res.ok || !path) throw new Error(data?.detail || data?.message || '文档上传失败');
      setDocumentPath(path);
      setDocumentName(data?.data?.file_name || file.name);
      message.success('需求文档已上传');
    } catch (err: any) {
      setDocumentPath('');
      setDocumentName('');
      message.error(err?.message || '文档上传失败');
    }
    return false;
  };

  const start = async () => {
    if (!isPageUrl(url)) {
      message.warning('Web 自动化测试需要填写完整的页面地址');
      return;
    }
    setBusy(true);
    setPhase('running');
    setError('');
    setResult(null);
    setCases([]);
    setLogs([]);
    sessionStorage.setItem('web_test_draft', JSON.stringify({ url, requirement }));
    try {
      const ran = await runAnalyzePipeline({
        requirement: buildWebRequirement(mode, url, requirement),
        imagePaths: imagePath ? [imagePath] : [],
        documentPaths: documentPath ? [documentPath] : [],
        taskType: 'web',
        execute: true,
        callbacks: {
          onSteps: setSteps,
          onLog: (line) => setLogs((prev) => [...prev, line]),
          onCases: setCases,
        },
      });
      setExecutionId(ran.executionId);
      setResult(ran.result);
      setPhase('done');
    } catch (err: any) {
      const text = err?.response?.data?.detail || err?.message || '测试失败';
      setError(text);
      message.error(text);
      setPhase('failed');
    } finally {
      setBusy(false);
    }
  };

  if (phase === 'done' && result) {
    return <TestResultView result={result} cases={cases} executionId={executionId} logs={logs} onRetest={() => setPhase('form')} onBack={onBack} />;
  }
  if (phase === 'running' || phase === 'failed') {
    return (
      <TestRunPanel
        title="正在执行 Web 自动化测试"
        subtitle={url}
        phase={phase}
        steps={steps}
        logs={logs}
        cases={cases}
        error={error}
        busy={busy}
        onBack={() => setPhase('form')}
        onRetry={start}
      />
    );
  }

  return (
    <div>
      <div className="product-hero">
        <p><button type="button" className="product-text-btn" onClick={onBack}>测试中心</button> / Web 自动化测试</p>
        <h1>创建 Web 测试任务</h1>
        <p>输入网页地址，AI 分析页面、生成测试步骤并用浏览器真实执行。</p>
      </div>

      <div className="product-card">
        <label className="product-label">测试目标 · 页面地址</label>
        <Input size="large" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com" />
        <p className="product-note">本地基础页：http://localhost:8000/fixtures/basic-web-app/</p>
      </div>

      <div className="product-two-col">
        <div className="product-card">
          <label className="product-label">页面截图（可选）</label>
          <Upload.Dragger accept="image/*" maxCount={1} showUploadList={false} beforeUpload={uploadImage}>
            {imagePreview ? <img src={imagePreview} alt="" className="product-upload-preview" /> : (
              <><p><PictureOutlined /></p><p>上传当前页面截图</p></>
            )}
          </Upload.Dragger>
        </div>
        <div className="product-card">
          <label className="product-label">需求文档（可选）</label>
          <Upload.Dragger maxCount={1} showUploadList={false} beforeUpload={uploadDocument}>
            <p><FileTextOutlined /></p>
            <p>{documentName || '上传 PRD / Word / PDF'}</p>
          </Upload.Dragger>
        </div>
      </div>

      <div className="product-card">
        <label className="product-label">测试目标描述</label>
        <Input.TextArea
          value={requirement}
          onChange={(e) => setRequirement(e.target.value)}
          placeholder={'例如：测试登录功能\n1. 输入账号密码\n2. 点击登录\n3. 验证进入首页'}
          autoSize={{ minRows: 4, maxRows: 8 }}
        />
      </div>

      <div className="product-card">
        <label className="product-label">测试模式</label>
        <div className="product-modes">
          {WEB_MODES.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`product-mode${modeId === item.id ? ' is-active' : ''}`}
              onClick={() => setModeId(item.id)}
            >
              <h3>{item.title}</h3>
              <p>{item.description}</p>
            </button>
          ))}
        </div>
        <div className="product-cta">
          <Button onClick={onBack}>返回测试中心</Button>
          <Button type="primary" size="large" loading={busy} onClick={start} style={{ marginLeft: 12, minWidth: 160 }}>
            开始 AI 测试
          </Button>
        </div>
      </div>
    </div>
  );
}
