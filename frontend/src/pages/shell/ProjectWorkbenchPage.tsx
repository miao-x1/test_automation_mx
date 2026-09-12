import { useEffect, useState } from 'react';
import { Drawer, Empty, message } from 'antd';
import { getCurrentProjectId, getCurrentProjectName, PROJECT_CHANGED } from '@/pages/product/projectStore';
import { fetchProjectUnderstanding } from '@/services/projectExplorer';
import { listTestTasks } from '@/services/projectTestTask';
import { fetchWorkspace } from '@/services/workspace';
import request from '@/services/request';
import { formatAgo } from './nav';
import './shell.css';

export default function ProjectWorkbenchPage() {
  const [panel, setPanel] = useState<'understand' | 'design' | 'tasks' | 'execute' | null>(null);
  const [understanding, setUnderstanding] = useState<any>(null);
  const [tasks, setTasks] = useState<any[]>([]);
  const [runs, setRuns] = useState<any[]>([]);
  const [activity, setActivity] = useState<any[]>([]);

  const load = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    try {
      const [u, t, workspace, exec] = await Promise.all([
        fetchProjectUnderstanding(projectId).catch(() => null),
        listTestTasks(projectId).catch(() => []),
        fetchWorkspace().catch(() => null),
        request.get('/executions/list', { params: { page: 1, page_size: 5, project_id: projectId } }).catch(() => null),
      ]);
      setUnderstanding(u);
      setTasks(t || []);
      const items = (exec as any)?.data?.items || (exec as any)?.items || [];
      setRuns(items);
      setActivity((workspace?.recent_activity || []).filter((item: any) => !item.project_id || item.project_id === projectId));
    } catch {
      message.error('加载工作台失败');
    }
  };

  useEffect(() => {
    void load();
    const reload = () => { void load(); };
    window.addEventListener(PROJECT_CHANGED, reload);
    return () => window.removeEventListener(PROJECT_CHANGED, reload);
  }, []);

  const scale = understanding?.scale || {};
  const name = getCurrentProjectName() || understanding?.project?.name || '当前项目';
  const running = tasks.filter((item) => ['running', '执行中'].includes(String(item.status || ''))).length;
  const latest = runs[0];
  const passRate = latest?.pass_rate ?? latest?.success_rate;

  return (
    <div className="pw-page">
      <div className="pw-head">
        <div>
          <h1>{name}</h1>
          <p>项目工作台</p>
          <p>最近更新：{formatAgo(understanding?.updated_at || latest?.created_at)}</p>
        </div>
      </div>
      <div className="wb-grid">
        <button type="button" className="wb-card" onClick={() => setPanel('understand')}>
          <h3>项目理解</h3>
          <p>{scale.pages ?? 0} 页面</p>
          <p>{scale.features ?? (understanding?.features || []).length} 功能</p>
          <p>{scale.apis ?? 0} API</p>
        </button>
        <button type="button" className="wb-card" onClick={() => setPanel('design')}>
          <h3>测试设计</h3>
          <p>{scale.cases ?? 0} 测试用例</p>
          <p>{tasks.reduce((sum, item) => sum + (item.case_count || 0), 0)} 任务内用例</p>
        </button>
        <button type="button" className="wb-card" onClick={() => setPanel('tasks')}>
          <h3>测试任务</h3>
          <p>{tasks.length} 个测试任务</p>
          <p>{running} 个进行中</p>
        </button>
        <button type="button" className="wb-card" onClick={() => setPanel('execute')}>
          <h3>测试执行</h3>
          <p>{latest ? `最近执行 ${latest.name || latest.job_name || latest.id}` : '还没有执行记录'}</p>
          <p>{passRate != null ? `${passRate}% 通过率` : '暂无通过率'}</p>
        </button>
      </div>
      <div className="wb-activity">
        <h3>最近活动</h3>
        {activity.length === 0 && runs.length === 0 ? <Empty description="还没有项目活动" /> : (
          <>
            {activity.slice(0, 6).map((item, index) => (
              <div key={`${item.title}-${index}`} className="wb-activity-row">
                <span>● {item.title}</span>
                <span>{formatAgo(item.at || item.created_at || item.updated_at)}</span>
              </div>
            ))}
            {activity.length === 0 ? runs.slice(0, 6).map((item) => (
              <div key={item.id} className="wb-activity-row">
                <span>● {item.name || item.job_name || `执行 #${item.id}`}</span>
                <span>{formatAgo(item.created_at || item.updated_at)}</span>
              </div>
            )) : null}
          </>
        )}
      </div>
      <Drawer
        title={panel === 'understand' ? '项目理解' : panel === 'design' ? '测试设计' : panel === 'tasks' ? '测试任务' : '测试执行'}
        open={!!panel}
        onClose={() => setPanel(null)}
        width={420}
      >
        {panel === 'understand' ? (
          <div>
            {(understanding?.features || []).map((item: any) => (
              <p key={item.id}>{item.name}　{item.entry_page || item.module || ''}</p>
            ))}
            {!(understanding?.features || []).length ? <Empty description="还没有解析到功能" /> : null}
          </div>
        ) : null}
        {panel === 'design' ? (
          <div>
            {tasks.map((item) => <p key={item.id}>{item.name}　{item.case_count || 0} 用例</p>)}
            {!tasks.length ? <Empty description="还没有测试任务里的用例" /> : null}
          </div>
        ) : null}
        {panel === 'tasks' ? (
          <div>
            {tasks.map((item) => <p key={item.id}>{item.name}　{item.status || 'draft'}</p>)}
            {!tasks.length ? <Empty description="还没有测试任务" /> : null}
          </div>
        ) : null}
        {panel === 'execute' ? (
          <div>
            {runs.map((item) => <p key={item.id}>{item.name || item.job_name || `执行 #${item.id}`}　{item.status || item.result || ''}</p>)}
            {!runs.length ? <Empty description="还没有执行记录" /> : null}
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
