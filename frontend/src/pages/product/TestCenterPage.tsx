import { useSearchParams } from 'react-router-dom';
import WebTestFlow from './WebTestFlow';
import VisualTestFlow from './VisualTestFlow';
import ApiTestFlow from './ApiTestFlow';
import AssetHubPage from './AssetHubPage';
import './product.css';

const CARDS = [
  {
    kind: 'web',
    title: 'Web 自动化测试',
    description: '输入网页地址，AI 分析页面、生成测试流程并用浏览器真实执行。',
    action: '创建 Web 测试',
  },
  {
    kind: 'visual',
    title: 'UI 视觉测试',
    description: '上传页面截图或设计稿，分析布局、元素和可见问题。填写地址后才会打开页面执行。',
    action: '创建视觉测试',
  },
  {
    kind: 'api',
    title: 'API 接口测试',
    description: '仅支持 Swagger/OpenAPI JSON。解析接口、生成参数并真实发请求。',
    action: '创建接口测试',
  },
  {
    kind: 'tasks',
    title: '测试任务',
    description: '当前项目已经创建的测试任务，来自真实分析记录。',
    action: '查看任务',
  },
  {
    kind: 'executions',
    title: '执行记录',
    description: '每次真实执行的状态、耗时和结果。',
    action: '查看执行',
  },
  {
    kind: 'reports',
    title: '测试报告',
    description: '已完成执行的报告、截图和失败分析。',
    action: '查看报告',
  },
];

export default function TestCenterPage() {
  const [params, setParams] = useSearchParams();
  const kind = params.get('kind') || '';

  const back = () => {
    const next = new URLSearchParams(params);
    next.set('tab', 'test');
    next.delete('kind');
    setParams(next);
  };

  const open = (nextKind: string) => {
    const next = new URLSearchParams(params);
    next.set('tab', 'test');
    next.set('kind', nextKind);
    if (nextKind === 'tasks' || nextKind === 'executions' || nextKind === 'reports') {
      next.set('hub', nextKind === 'executions' ? 'executions' : nextKind);
    } else {
      next.delete('hub');
    }
    setParams(next);
  };

  if (kind === 'web') return <WebTestFlow onBack={back} />;
  if (kind === 'visual') return <VisualTestFlow onBack={back} />;
  if (kind === 'api') return <ApiTestFlow onBack={back} />;
  if (kind === 'tasks' || kind === 'executions' || kind === 'reports') {
    return (
      <div>
        <p><button type="button" className="product-text-btn" onClick={back}>测试中心</button></p>
        <AssetHubPage />
      </div>
    );
  }

  return (
    <div>
      <div className="product-hero">
        <h1>测试中心</h1>
        <p>不同类型走不同流程。不会再把所有测试都送进同一个输入框。</p>
      </div>
      <div className="product-grid">
        {CARDS.map((card) => (
          <button key={card.kind} type="button" className="product-tile" onClick={() => open(card.kind)}>
            <strong>{card.title}</strong>
            <span>{card.description}</span>
            <em>{card.action}</em>
          </button>
        ))}
      </div>
      <p className="product-note" style={{ marginTop: 16 }}>
        回归测试在「回归」页，页面性能在「效能测评」。兼容性多浏览器、移动端当前没有独立执行引擎，因此没有做成空卡片。
      </p>
    </div>
  );
}
