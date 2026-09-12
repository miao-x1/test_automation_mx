import { Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Input } from 'antd';
import { HeaderTools } from './ProjectHeaderBar';
import './shell.css';

export default function CenterLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const onProjects = location.pathname.startsWith('/projects');

  return (
    <div className="pc">
      <header className="pc-top">
        <button type="button" className="pc-brand" onClick={() => navigate('/projects')}>
          <span className="pc-mark">◈</span>
          <b>自动化测试平台</b>
        </button>
        <div className="pc-top-right">
          {onProjects ? (
            <Input
              allowClear
              className="pc-search"
              placeholder="搜索项目"
              value={params.get('q') || ''}
              onChange={(e) => setParams(e.target.value ? { q: e.target.value } : {})}
            />
          ) : null}
          <HeaderTools />
        </div>
      </header>
      <main className="pc-main">
        <Outlet />
      </main>
    </div>
  );
}
