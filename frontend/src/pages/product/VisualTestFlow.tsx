import { useState } from 'react';
import { Button, Input, Upload, message } from 'antd';
import { PictureOutlined } from '@ant-design/icons';
import { browserApiUrl } from '@/utils/apiUrl';
import { assertUploadAllowed, formatUploadError } from '@/utils/uploadGuard';
import { buildVisualRequirement } from './testModes';
import { isPageUrl, type UserStep } from './helpers';
import { runAnalyzePipeline } from './runWebPipeline';
import TestRunPanel from './TestRunPanel';
import TestResultView from './TestResultView';
import './product.css';

type Phase = 'form' | 'running' | 'failed' | 'done';

export default function VisualTestFlow({ onBack }: { onBack: () => void }) {
  const [url, setUrl] = useState('');
  const [requirement, setRequirement] = useState('');
  const [imagePath, setImagePath] = useState('');
  const [imagePreview, setImagePreview] = useState('');
  const [phase, setPhase] = useState<Phase>('form');
  const [steps, setSteps] = useState<UserStep[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [cases, setCases] = useState<any[]>([]);
  const [executionId, setExecutionId] = useState<number | null>(null);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

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
      message.success('截图已上传');
    } catch (err) {
      setImagePath('');
      setImagePreview('');
      message.error(formatUploadError(err));
    }
    return false;
  };

  const start = async () => {
    if (!imagePath) {
      message.warning('UI 视觉测试必须上传页面截图或设计稿');
      return;
    }
    if (url && !isPageUrl(url)) {
      message.warning('如需同时打开页面，请填写完整 http/https 地址');
      return;
    }
    setBusy(true);
    setPhase('running');
    setError('');
    setLogs([]);
    setCases([]);
    try {
      const ran = await runAnalyzePipeline({
        requirement: buildVisualRequirement(url, requirement),
        imagePaths: [imagePath],
        taskType: 'web',
        execute: isPageUrl(url),
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
      const text = err?.response?.data?.detail || err?.message || '视觉分析失败';
      setError(text);
      message.error(text);
      setPhase('failed');
    } finally {
      setBusy(false);
    }
  };

  if (phase === 'done' && result) {
    return <TestResultView result={result} cases={cases} executionId={executionId} onRetest={() => setPhase('form')} onBack={onBack} />;
  }
  if (phase === 'running' || phase === 'failed') {
    return (
      <TestRunPanel
        title="正在分析界面"
        subtitle={url || '仅截图分析'}
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
        <p><button type="button" className="product-text-btn" onClick={onBack}>测试中心</button> / UI 视觉测试</p>
        <h1>创建视觉测试</h1>
        <p>只有截图时只做图片分析，不会假装跑过浏览器。截图加地址时会打开网页并按分析结果执行；当前没有像素级设计稿对比引擎。</p>
      </div>
      <div className="product-card">
        <label className="product-label">页面截图 / 设计稿</label>
        <Upload.Dragger accept="image/*" maxCount={1} showUploadList={false} beforeUpload={uploadImage}>
          {imagePreview ? <img src={imagePreview} alt="" className="product-upload-preview" /> : (
            <><p style={{ fontSize: 36 }}><PictureOutlined /></p><p>上传截图或设计稿</p></>
          )}
        </Upload.Dragger>
      </div>
      <div className="product-card">
        <label className="product-label">目标页面（可选，填写后才会真实执行）</label>
        <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com" />
      </div>
      <div className="product-card">
        <label className="product-label">检查要求</label>
        <Input.TextArea
          value={requirement}
          onChange={(e) => setRequirement(e.target.value)}
          placeholder="例如：检查登录页按钮是否可见，文案是否完整，布局是否错位"
          autoSize={{ minRows: 3, maxRows: 6 }}
        />
        <div className="product-cta">
          <Button onClick={onBack}>返回测试中心</Button>
          <Button type="primary" size="large" loading={busy} onClick={start} style={{ marginLeft: 12 }}>开始视觉分析</Button>
        </div>
      </div>
    </div>
  );
}
