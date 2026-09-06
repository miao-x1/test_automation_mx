import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Button, Empty, Popconfirm, Table, Tabs, Tag, message } from 'antd';
import request from '@/services/request';
import { extractPageUrl, parseCases, passRate, unwrap } from './helpers';
import { getCurrentProjectId, PROJECT_CHANGED } from './projectStore';
import './product.css';

const STATUS_TEXT: Record<string, { color: string; text: string }> = {
  pending: { color: 'orange', text: '等待中' },
  running: { color: 'blue', text: '执行中' },
  analyzing: { color: 'blue', text: '分析中' },
  success: { color: 'green', text: '成功' },
  completed: { color: 'green', text: '已完成' },
  failed: { color: 'red', text: '失败' },
  cancelled: { color: 'default', text: '已取消' },
  waiting: { color: 'orange', text: '等待中' },
};

const TYPE_TEXT: Record<string, string> = {
  web: '功能 / 界面',
  api: '接口',
  android: '移动端',
  performance: '性能',
};

export default function AssetHubPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const parentTab = params.get('tab');
  const tab = params.get('hub') || (parentTab === 'reports' ? 'reports' : 'tasks');
  const [tasks, setTasks] = useState<any[]>([]);
  const [executions, setExecutions] = useState<any[]>([]);
  const [cases, setCases] = useState<any[]>([]);
  const [shots, setShots] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const projectId = getCurrentProjectId();
      const [taskRes, execRes]: any[] = await Promise.all([
        request.get('/requirement/list', { params: { page: 1, page_size: 50, project_id: projectId || undefined } }),
        request.get('/executions/list', { params: { page: 1, page_size: 50, project_id: projectId || undefined } }),
      ]);
      const taskItems = unwrap(taskRes)?.items || [];
      const execItems = unwrap(execRes)?.items || [];
      setTasks(taskItems);
      setExecutions(execItems);

      const caseRows: any[] = [];
      for (const task of taskItems.slice(0, 20)) {
        try {
          const detailRes: any = await request.get(`/requirement/${task.id}`);
          const detail = unwrap(detailRes);
          parseCases(detail?.generated_case).forEach((c: any, i: number) => {
            caseRows.push({
              key: `${task.id}-${i}`,
              title: c.title || c.name || `用例 ${i + 1}`,
              page: extractPageUrl(detail.requirement || task.requirement),
              type: TYPE_TEXT[task.task_type] || '页面测试',
              steps: Array.isArray(c.steps) ? c.steps.length : (c.steps ? 1 : 0),
              updated_at: detail.updated_at || task.created_at,
              last: task.status,
              taskId: task.id,
            });
          });
        } catch {
          /* skip broken tasks */
        }
      }
      setCases(caseRows);

      const shotRows = execItems
        .filter((item: any) => item.screenshot_path)
        .map((item: any) => ({
          id: item.id,
          name: `测试截图 #${item.id}`,
          page: item.base_url || '',
          time: item.end_time || item.created_at,
          url: `/api/executions/${item.id}/screenshot`,
        }));
      setShots(shotRows);
    } catch {
      message.error('加载资产失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const reload = () => load();
    window.addEventListener(PROJECT_CHANGED, reload);
    return () => window.removeEventListener(PROJECT_CHANGED, reload);
  }, [load]);

  const removeTask = async (id: number) => {
    try {
      await request.delete(`/requirement/${id}`);
      message.success('已删除');
      load();
    } catch {
      message.error('删除失败');
    }
  };

  const statusTag = (status?: string) => {
    const meta = STATUS_TEXT[status || ''] || { color: 'default', text: status || '-' };
    return <Tag color={meta.color}>{meta.text}</Tag>;
  };

  return (
    <div className="product-shell">
      <div className="product-hero">
        <h1>{params.get('kind') === 'executions' ? '执行记录' : params.get('kind') === 'reports' ? '测试报告' : params.get('kind') === 'tasks' ? '测试任务' : '资产中心'}</h1>
        <p>这里只显示当前项目已经真实产生的测试任务、执行记录、报告和截图。</p>
      </div>
      <div className="product-card" style={{ paddingTop: 8 }}>
        <Tabs
          activeKey={tab}
          onChange={(key) => {
            const next = new URLSearchParams(params);
            next.set('hub', key);
            setParams(next);
          }}
          items={[
            {
              key: 'tasks',
              label: '测试任务',
              children: (
                <Table
                  rowKey="id"
                  loading={loading}
                  dataSource={tasks}
                  locale={{ emptyText: <Empty description="还没有测试任务。去开始一次测试后会出现在这里。" /> }}
                  columns={[
                    { title: '任务名称', dataIndex: 'task_name', ellipsis: true },
                    { title: '测试页面', render: (_: unknown, r: any) => extractPageUrl(r.requirement) || '-' },
                    { title: '测试类型', dataIndex: 'task_type', render: (v: string) => TYPE_TEXT[v] || '页面测试' },
                    { title: '执行时间', dataIndex: 'created_at' },
                    { title: '状态', dataIndex: 'status', render: statusTag },
                    {
                      title: '通过率',
                      render: (_: unknown, r: any) => {
                        const exec = executions.find((e) => e.task_id && e.task_id === r.task_id);
                        if (!exec) return '-';
                        return `${passRate(exec.success_count || 0, exec.failed_count || 0)}%`;
                      },
                    },
                    {
                      title: '操作',
                      width: 220,
                      render: (_: unknown, r: any) => (
                        <>
                          <Button type="link" onClick={() => navigate(`/test/task/${r.id}`)}>查看</Button>
                          <Button type="link" onClick={() => navigate(`/workspace/project/${getCurrentProjectId()}?tab=test&kind=web&rerun=${r.id}`)}>重新测试</Button>
                          <Popconfirm title="删除这个测试任务？" onConfirm={() => removeTask(r.id)}>
                            <Button type="link" danger>删除</Button>
                          </Popconfirm>
                        </>
                      ),
                    },
                  ]}
                />
              ),
            },
            {
              key: 'cases',
              label: '测试用例',
              children: (
                <Table
                  rowKey="key"
                  loading={loading}
                  dataSource={cases}
                  locale={{ emptyText: <Empty description="还没有从真实分析中生成的测试用例。" /> }}
                  columns={[
                    { title: '用例名称', dataIndex: 'title' },
                    { title: '测试页面', dataIndex: 'page', render: (v: string) => v || '-' },
                    { title: '测试类型', dataIndex: 'type' },
                    { title: '测试步骤', dataIndex: 'steps' },
                    { title: '最近执行结果', dataIndex: 'last', render: statusTag },
                    { title: '更新时间', dataIndex: 'updated_at' },
                  ]}
                />
              ),
            },
            {
              key: 'executions',
              label: '执行记录',
              children: (
                <Table
                  rowKey="id"
                  loading={loading}
                  dataSource={executions}
                  locale={{ emptyText: <Empty description="还没有执行记录。" /> }}
                  columns={[
                    { title: '执行 ID', dataIndex: 'id' },
                    { title: '状态', dataIndex: 'status', render: statusTag },
                    { title: '通过', dataIndex: 'success_count' },
                    { title: '失败', dataIndex: 'failed_count' },
                    { title: '开始时间', dataIndex: 'start_time', render: (v: string, r: any) => v || r.created_at },
                    { title: '结束时间', dataIndex: 'end_time' },
                    {
                      title: '操作',
                      render: (_: unknown, r: any) => (
                        <Button type="link" onClick={() => window.open(`/api/executions/${r.id}/report?format=html`, '_blank')}>
                          查看
                        </Button>
                      ),
                    },
                  ]}
                />
              ),
            },
            {
              key: 'reports',
              label: '测试报告',
              children: (
                <Table
                  rowKey="id"
                  loading={loading}
                  dataSource={executions.filter((e) => ['success', 'failed', 'cancelled'].includes(e.status))}
                  locale={{ emptyText: <Empty description="还没有完成的测试报告。" /> }}
                  columns={[
                    { title: '报告名称', render: (_: unknown, r: any) => `测试报告 #${r.id}` },
                    { title: '测试页面', render: (_: unknown, r: any) => r.base_url || '-' },
                    { title: '测试时间', dataIndex: 'end_time', render: (v: string, r: any) => v || r.created_at },
                    { title: '测试结果', dataIndex: 'status', render: statusTag },
                    {
                      title: '通过率',
                      render: (_: unknown, r: any) => `${passRate(r.success_count || 0, r.failed_count || 0)}%`,
                    },
                    {
                      title: '操作',
                      render: (_: unknown, r: any) => (
                        <Button type="link" onClick={() => window.open(`/api/executions/${r.id}/report?format=html`, '_blank')}>
                          查看
                        </Button>
                      ),
                    },
                  ]}
                />
              ),
            },
            {
              key: 'shots',
              label: '测试截图',
              children: shots.length === 0 ? (
                <Empty description="还没有执行过程中保存的截图。" />
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 16 }}>
                  {shots.map((s) => (
                    <a key={s.id} href={s.url} target="_blank" rel="noreferrer" className="product-card" style={{ margin: 0 }}>
                      <img src={s.url} alt={s.name} style={{ width: '100%', borderRadius: 8 }} />
                      <div style={{ marginTop: 8 }}>{s.name}</div>
                      <div className="product-note">{s.time || ''}</div>
                    </a>
                  ))}
                </div>
              ),
            },
          ]}
        />
      </div>
    </div>
  );
}
