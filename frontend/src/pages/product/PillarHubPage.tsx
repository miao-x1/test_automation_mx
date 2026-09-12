import { useNavigate } from 'react-router-dom';
import { HUB_LINKS, PILLARS, type PillarKey } from './pillarNav';
import './product.css';

export default function PillarHubPage({ pillar }: { pillar: Exclude<PillarKey, 'workspace'> }) {
  const navigate = useNavigate();
  const current = PILLARS.find((item) => item.key === pillar);
  const items = HUB_LINKS[pillar];

  return (
    <div className="product-shell product-wide">
      <div className="product-hero">
        <p>{PILLARS.map((item) => item.name).join(' → ')}</p>
        <h1>{current?.name}</h1>
        <p>{current?.summary}。这里只展示已有功能入口，后续版本变化继续基于已有资产做增量，而不是另建一套测试体系。</p>
      </div>

      <div className="product-card">
        <h2>本板块功能</h2>
        <div className="product-modes">
          {items.map((item) => (
            <button
              key={item.path + item.title}
              type="button"
              className="product-mode"
              onClick={() => navigate(item.path)}
            >
              <h3>{item.title}</h3>
              <p>{item.desc}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
