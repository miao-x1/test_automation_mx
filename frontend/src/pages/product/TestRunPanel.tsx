import { Button, Collapse } from 'antd';
import type { UserStep } from './helpers';
import './product.css';

type Props = {
  title: string;
  subtitle?: string;
  phase: 'running' | 'failed';
  steps: UserStep[];
  logs: string[];
  cases?: any[];
  error?: string;
  busy?: boolean;
  onBack: () => void;
  onRetry?: () => void;
};

export default function TestRunPanel({
  title,
  subtitle,
  phase,
  steps,
  logs,
  cases = [],
  error,
  busy,
  onBack,
  onRetry,
}: Props) {
  const done = steps.filter((s) => s.status === 'finish' || s.status === 'skip').length;
  const total = Math.max(steps.length, 1);
  const percent = phase === 'failed' ? done : Math.min(99, Math.round((done / total) * 100) || 8);
  const current = steps.find((s) => s.status === 'process') || steps.find((s) => s.status === 'wait');

  return (
    <div>
      <div className="product-hero">
        <h1>{phase === 'failed' ? '测试未完成' : title}</h1>
        <p>{subtitle}</p>
        <p>状态：{phase === 'failed' ? '失败' : '运行中'}</p>
        <div className="product-progress">
          <div className="product-progress-bar" style={{ width: `${percent}%` }} />
        </div>
        <p className="product-note">{percent}% · {current?.label || '处理中'}</p>
      </div>
      <div className="product-card">
        <h2>执行阶段</h2>
        <ul className="product-steps">
          {steps.map((step) => (
            <li key={step.key}>
              <span className="product-dot">
                {step.status === 'finish' || step.status === 'skip' ? '✓' : step.status === 'error' ? '✕' : step.status === 'process' ? '▶' : '○'}
              </span>
              <div>
                <div>{step.label}</div>
                {step.detail && <div className="product-note">{step.detail}</div>}
              </div>
            </li>
          ))}
          {cases.slice(0, 8).map((item, index) => (
            <li key={`case-${index}`}>
              <span className="product-dot">●</span>
              <div>已生成 {item.title || item.name || `步骤 ${index + 1}`}</div>
            </li>
          ))}
        </ul>
        {error && <div className="product-fail" style={{ marginTop: 16 }}>{error}</div>}
        <div className="product-cta" style={{ gap: 12 }}>
          <Button onClick={onBack} disabled={busy}>返回修改</Button>
          {phase === 'failed' && onRetry && <Button type="primary" onClick={onRetry} disabled={busy}>重新测试</Button>}
        </div>
      </div>
      <div className="product-card">
        <h2>实时日志</h2>
        {logs.length === 0 ? <p className="product-note">等待执行日志</p> : (
          <pre className="product-log">{logs.join('\n')}</pre>
        )}
      </div>
      <Collapse
        ghost
        items={[{
          key: 'tech',
          label: '技术详情',
          children: <p className="product-note">执行过程由项目已有分析与浏览器测试引擎完成，这里只展示产品进度。</p>,
        }]}
      />
    </div>
  );
}
