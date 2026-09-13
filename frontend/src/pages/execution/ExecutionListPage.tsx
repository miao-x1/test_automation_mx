import { useState, useEffect, useCallback } from 'react';
import { Card, Drawer, Descriptions, Table, Button, Tag, Space, message, Tabs, Progress, Tooltip } from 'antd';
import { ReloadOutlined, EyeOutlined } from '@ant-design/icons';
import request from '@/services/request';
import { getCurrentProjectId, getCurrentProjectName, PROJECT_CHANGED } from '@/pages/product/projectStore';
import { openProjectAgent } from '@/services/projectExplorer';
import { operateTestTask } from '@/services/projectTestTask';
import '../shell/shell.css';

/** 格式化耗时：2.5s / 45.8s / 1m 23s / 1h 5m 3s */
function formatDuration(d?: number): string {
  if (!d && d !== 0) return '-';
  if (d < 60) return `${d.toFixed(1)}s`;
  const m = Math.floor(d / 60);
  const s = Math.round(d % 60);
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return `${h}h ${rm}m ${s}s`;
}

/** 判断是否包含AI分析标记 */
function hasAIAnalysis(r: any): boolean {
  if (!r?.analysis_result) return false;
  try {
    const parsed = typeof r.analysis_result === 'string' ? JSON.parse(r.analysis_result) : r.analysis_result;
    return parsed?.ai_analyzed === true;
  } catch {
    return false;
  }
}

export default function ExecutionListPage() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [activeTab, setActiveTab] = useState('all');
  const [projectName, setProjectName] = useState(getCurrentProjectName());
  const [detail, setDetail] = useState<any | null>(null);
  const [detailLogs, setDetailLogs] = useState('');
  const [showReport, setShowReport] = useState(false);
  const [pane, setPane] = useState<'overview' | 'records' | 'live' | 'fail'>('records');

  const openDetail = async (row: any, report = false) => {
    setShowReport(report);
    setDetail(row);
    setDetailLogs('');
    try {
      const res: any = await request.get(`/executions/${row.id}`);
      setDetail(res?.data || res || row);
    } catch {
      setDetail(row);
    }
    try {
      const res: any = await request.get(`/executions/${row.id}/logs`, {
        responseType: 'text',
        transformResponse: [(value: string) => value],
      });
      setDetailLogs(typeof res === 'string' ? res : res?.data || '');
    } catch {
      setDetailLogs('');
    }
  };

  const retryRun = async (row: any) => {
    try {
      const res = await fetch(`/api/executions/${row.id}/retry`, { method: 'POST', credentials: 'include' });
      const data = await res.json();
      const packed = data.data || data;
      if (packed.execution_id) {
        message.success(`重试已提交 #${packed.execution_id}`);
        fetchData(page, pageSize, activeTab);
      } else {
        message.error(data.message || '重试失败');
      }
    } catch {
      message.error('重试失败');
    }
  };

  const createDefect = async (row: any) => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    if (row.task_id) {
      try {
        await operateTestTask(projectId, row.task_id, 'create_bug');
        message.success('已在当前任务写入缺陷');
        return;
      } catch (err: any) {
        message.error(err?.response?.data?.detail || '写入缺陷失败');
      }
    }
    openProjectAgent(`为执行 #${row.id} 创建缺陷`);
  };

  const fetchData = useCallback(async (p: number, ps: number, status?: string) => {
    setLoading(true);
    try {
      const res: any = await request.get('/executions/list', {
        params: { page: p, page_size: ps, status: status === 'all' ? undefined : status, project_id: getCurrentProjectId() || undefined },
      });
      const d = res.data || res;
      setData(d?.items || []);
      setTotal(d?.total || 0);
    } catch {
      message.error('加载执行列表失败');
      setData([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(page, pageSize, activeTab); }, [page, pageSize, activeTab, fetchData]);
  useEffect(() => {
    const reload = () => {
      setProjectName(getCurrentProjectName());
      fetchData(1, pageSize, activeTab);
    };
    window.addEventListener(PROJECT_CHANGED, reload);
    return () => window.removeEventListener(PROJECT_CHANGED, reload);
  }, [fetchData, pageSize, activeTab]);

  const statusMap: Record<string, { color: string; text: string }> = {
    success: { color: 'green', text: '成功' },
    failed: { color: 'red', text: '失败' },
    running: { color: 'blue', text: '执行中' },
    waiting: { color: 'orange', text: '等待中' },
    cancelled: { color: 'default', text: '已取消' },
    pending: { color: 'orange', text: '排队中' },
  };

  const running = data.filter((item) => item.status === 'running' || item.status === 'pending');
  const failed = data.filter((item) => item.status === 'failed');
  const passed = data.filter((item) => item.status === 'success');
  const live = running[0];

  return (
    <div className="pw-page">
      <div className="pw-head">
        <div>
          <h1>测试执行</h1>
          <p>只看当前项目{projectName ? `「${projectName}」` : ''}的执行记录。</p>
        </div>
        <Space>
          <Button onClick={() => openProjectAgent('分析失败用例')}>✦ 分析失败用例</Button>
          <Button icon={<ReloadOutlined />} onClick={() => fetchData(page, pageSize, activeTab)}>刷新</Button>
        </Space>
      </div>
      <div className="sub-tabs">
        <button type="button" className={pane === 'overview' ? 'is-on' : ''} onClick={() => setPane('overview')}>执行概览</button>
        <button type="button" className={pane === 'records' ? 'is-on' : ''} onClick={() => { setPane('records'); setActiveTab('all'); }}>执行记录</button>
        <button type="button" className={pane === 'live' ? 'is-on' : ''} onClick={() => { setPane('live'); setActiveTab('running'); setPage(1); }}>实时执行</button>
        <button type="button" className={pane === 'fail' ? 'is-on' : ''} onClick={() => { setPane('fail'); setActiveTab('failed'); setPage(1); }}>失败分析</button>
      </div>
      {pane === 'overview' ? (
        <div className="uw-panel" style={{ marginBottom: 16 }}>
          <p>总记录 {total} · 当前页通过 {passed.length} · 失败 {failed.length} · 执行中 {running.length}</p>
          {live ? (
            <>
              <p>正在执行：{live.name || live.job_name || `#${live.id}`}</p>
              {(() => {
                const done = (live.success_count || 0) + (live.failed_count || 0) + (live.skip_count || live.skipped_count || 0);
                const all = live.total_count || live.case_count || done;
                const rate = all > 0 ? Math.round((done / all) * 100) : 0;
                return all > 0 ? <Progress percent={rate} size="small" /> : null;
              })()}
            </>
          ) : <p>当前没有进行中的执行。</p>}
        </div>
      ) : null}
      {pane === 'fail' && !failed.length ? <p style={{ color: 'var(--text-muted)' }}>当前项目这一页没有失败记录。</p> : null}
      <Card
        title={null}
        extra={null}
      >
        <Tabs
          activeKey={activeTab}
          onChange={(k) => { setActiveTab(k); setPage(1); }}
          items={[
            { key: 'all', label: '全部' },
            { key: 'running', label: '执行中' },
            { key: 'success', label: '成功' },
            { key: 'failed', label: '失败' },
          ]}
        />

        <Table
          dataSource={data}
          rowKey="id"
          loading={loading}
          size="middle"
          scroll={{ x: 1300 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); },
          }}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 70 },
            { title: '类型', dataIndex: 'execution_type', width: 100,
              render: (t: string) => {
                const map: Record<string, { color: string; text: string }> = {
                  web: { color: 'blue', text: 'Web' },
                  api: { color: 'cyan', text: 'API' },
                  android: { color: 'geekblue', text: 'Android' },
                  suite: { color: 'purple', text: '套件' },
                  batch: { color: 'magenta', text: '批量' },
                };
                const info = map[t] || { color: 'default', text: t };
                return <Tag color={info.color}>{info.text}</Tag>;
              },
            },
            { title: '状态', dataIndex: 'status', width: 100,
              render: (s: string) => {
                const info = statusMap[s] || { color: 'default', text: s };
                return <Tag color={info.color}>{info.text}</Tag>;
              },
            },
            { title: '通过率', width: 150,
              render: (_, r: any) => {
                const total = (r.success_count || 0) + (r.failed_count || 0);
                const rate = total > 0 ? Math.round((r.success_count || 0) / total * 100) : 0;
                return (
                  <div style={{ minWidth: 100 }}>
                    <Progress percent={rate} size="small" strokeColor={rate >= 80 ? '#52c41a' : rate >= 50 ? '#faad14' : '#ff4d4f'} />
                  </div>
                );
              },
            },
            { title: '通过/失败', width: 130,
              render: (_, r: any) => (
                <Space size={4}>
                  <Tag color="green">{r.success_count || 0} 通过</Tag>
                  <Tag color="red">{r.failed_count || 0} 失败</Tag>
                </Space>
              ),
            },
            { title: 'AI分析', width: 90,
              render: (_: any, r: any) => hasAIAnalysis(r) ? <Tag color="geekblue">AI分析</Tag> : <Tag>无</Tag>,
            },
            { title: '耗时', dataIndex: 'duration', width: 110,
              render: (d: number) => formatDuration(d),
            },
            { title: '任务ID', dataIndex: 'task_id', width: 80, render: (id: number) => id || '-' },
            { title: '执行时间', dataIndex: 'start_time', width: 180, render: (t: string) => t || '-' },
            { title: '操作', width: 200, fixed: 'right' as const,
              render: (_: any, r: any) => (
                <Space>
                  <Tooltip title="执行详情">
                    <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => { void openDetail(r, false); }}>执行详情</Button>
                  </Tooltip>
                  <Button type="link" size="small" onClick={() => { void openDetail(r, true); }}>报告</Button>
                </Space>
              ),
            },
          ]}
        />
      </Card>
      <Drawer
        title={detail ? `执行 #${detail.id}` : '执行详情'}
        open={!!detail}
        onClose={() => { setDetail(null); setShowReport(false); setDetailLogs(''); }}
        width={720}
      >
        {detail ? (
          showReport ? (
            <iframe
              title={`执行报告 ${detail.id}`}
              src={`/api/executions/${detail.id}/report?format=html`}
              style={{ width: '100%', height: '70vh', border: '1px solid #d0d7de' }}
            />
          ) : (
            <>
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="状态">{detail.status || '-'}</Descriptions.Item>
              <Descriptions.Item label="类型">{detail.execution_type || '-'}</Descriptions.Item>
              <Descriptions.Item label="任务">{detail.task_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="通过">{detail.success_count ?? 0}</Descriptions.Item>
              <Descriptions.Item label="失败">{detail.failed_count ?? 0}</Descriptions.Item>
              <Descriptions.Item label="耗时">{formatDuration(detail.duration)}</Descriptions.Item>
              <Descriptions.Item label="开始时间">{detail.start_time || '-'}</Descriptions.Item>
              <Descriptions.Item label="结束时间">{detail.end_time || '-'}</Descriptions.Item>
              <Descriptions.Item label="AI 分析">{hasAIAnalysis(detail) ? '有' : '无'}</Descriptions.Item>
              {detail.expected_result || detail.expected ? <Descriptions.Item label="预期">{detail.expected_result || detail.expected}</Descriptions.Item> : null}
              {detail.actual_result || detail.actual ? <Descriptions.Item label="实际">{detail.actual_result || detail.actual}</Descriptions.Item> : null}
              {detail.error_message ? <Descriptions.Item label="错误">{detail.error_message}</Descriptions.Item> : null}
              {detailLogs ? (
                <Descriptions.Item label="执行日志">
                  <pre style={{ whiteSpace: 'pre-wrap', margin: 0, maxHeight: 240, overflow: 'auto' }}>{detailLogs}</pre>
                </Descriptions.Item>
              ) : null}
              {(detail.screenshot || detail.screenshot_url) ? (
                <Descriptions.Item label="截图">
                  <img src={detail.screenshot || detail.screenshot_url} alt="执行截图" style={{ maxWidth: '100%' }} />
                </Descriptions.Item>
              ) : null}
              {detail.related_code || detail.source_file ? <Descriptions.Item label="相关代码">{detail.related_code || detail.source_file}</Descriptions.Item> : null}
              {detail.analysis_result ? (
                <Descriptions.Item label="分析结果">
                  <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                    {typeof detail.analysis_result === 'string' ? detail.analysis_result : JSON.stringify(detail.analysis_result, null, 2)}
                  </pre>
                </Descriptions.Item>
              ) : null}
            </Descriptions>
            <Space style={{ marginTop: 12 }}>
              <Button onClick={() => void retryRun(detail)}>重新执行</Button>
              <Button onClick={() => openProjectAgent(`分析失败用例 执行 #${detail.id}`)}>分析失败原因</Button>
              <Button onClick={() => void createDefect(detail)}>创建缺陷</Button>
            </Space>
            </>
          )
        ) : null}
      </Drawer>
    </div>
  );
}
