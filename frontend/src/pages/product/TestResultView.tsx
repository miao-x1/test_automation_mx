import { Button } from 'antd';
import { flattenResultCases, passRate } from './helpers';
import './product.css';

type Props = {
  result: any;
  cases?: any[];
  executionId?: number | null;
  logs?: string[];
  onRetest: () => void;
  onBack?: () => void;
};

export default function TestResultView({ result, cases = [], executionId, logs = [], onRetest, onBack }: Props) {
  const rows = flattenResultCases(result);
  const passed = rows.filter((r) => r.status === 'pass').length || result.success_count || 0;
  const failed = rows.filter((r) => r.status === 'fail').length || result.failed_count || 0;
  const skipped = rows.filter((r) => r.status === 'skip').length;
  const rate = passRate(passed, failed, skipped);
  const failedStatus = String(result?.status || '').toLowerCase() === 'failed' || failed > 0;
  const screenshotUrl = executionId ? `/api/executions/${executionId}/screenshot` : '';
  const logText = result?.log_content || logs.join('\n');
  const analysis = result?.analysis || {};
  const generatedSteps = cases.filter((item) => item.title || item.name || item.steps);

  return (
    <div>
      <div className="product-hero">
        <h1>{failedStatus ? '测试失败' : '测试报告'}</h1>
        <p>{failedStatus ? '这次执行没有通过。下面是真实失败原因，不是模拟成功。' : '下面是这次真实执行的结果。'}</p>
        {result?.error_message && <p className="product-fail">{result.error_message}</p>}
      </div>

      <div className="product-card">
        <h2>测试概览</h2>
        <div className="product-summary">
          <div className="product-stat"><span>通过</span><b className="product-pass">{passed}</b></div>
          <div className="product-stat"><span>失败</span><b className="product-fail">{failed}</b></div>
          <div className="product-stat"><span>跳过</span><b className="product-skip">{skipped}</b></div>
          <div className="product-stat"><span>通过率</span><b>{rate}%</b></div>
        </div>
        <p>状态：{failedStatus ? 'FAILED' : String(result?.status || 'SUCCESS').toUpperCase()}</p>
      </div>

      <div className="product-card">
        <h2>测试步骤</h2>
        {generatedSteps.length === 0 && rows.length === 0 && <p className="product-note">没有可展示的步骤。</p>}
        {generatedSteps.map((item, index) => (
          <div key={`step-${index}`} className="product-result-item">
            <span>{item.title || item.name || `步骤 ${index + 1}`}</span>
            <em>{Array.isArray(item.steps) ? `${item.steps.length} 步` : ''}</em>
          </div>
        ))}
        {rows.map((item) => (
          <div className="product-result-item" key={item.key}>
            <div>
              <span className={item.status === 'fail' ? 'product-fail' : item.status === 'skip' ? 'product-skip' : 'product-pass'}>
                {item.status === 'fail' ? '✕ FAILED' : item.status === 'skip' ? '○ SKIP' : '✓ PASS'}
              </span>
              {' '}{item.title}
              {item.steps && <div className="product-note">{item.steps}</div>}
            </div>
          </div>
        ))}
      </div>

      <div className="product-card">
        <h2>执行日志</h2>
        {logText ? <pre className="product-log">{logText}</pre> : <p className="product-note">这次执行没有留下可展示日志。</p>}
      </div>

      <div className="product-card">
        <h2>截图</h2>
        {screenshotUrl ? (
          <img src={screenshotUrl} alt="执行截图" className="product-upload-preview" style={{ maxHeight: 360 }} />
        ) : (
          <p className="product-note">这次执行没有保存截图。</p>
        )}
      </div>

      <div className="product-card">
        <h2>失败原因</h2>
        {failedStatus ? (
          <>
            <p className="product-fail">{analysis.fail_step || analysis.root_cause || result?.error_message || '执行失败'}</p>
            {rows.filter((item) => item.status === 'fail').map((item) => (
              <div key={`fail-${item.key}`} className="product-note">
                {item.title}：{item.reason || item.actual || '未通过'}
              </div>
            ))}
          </>
        ) : (
          <p className="product-note">没有失败项。</p>
        )}
      </div>

      <div className="product-card">
        <h2>AI 分析建议</h2>
        <p>{analysis.suggestion || analysis.fix_suggestion || analysis.root_cause || '这次没有额外的分析建议。'}</p>
        <div className="product-cta" style={{ gap: 12 }}>
          {onBack && <Button onClick={onBack}>返回</Button>}
          {executionId && (
            <Button onClick={() => window.open(`/api/executions/${executionId}/report?format=html`, '_blank')}>
              打开完整报告
            </Button>
          )}
          <Button type="primary" onClick={onRetest}>重新测试</Button>
        </div>
      </div>
    </div>
  );
}
