import { useState, useEffect, useCallback } from 'react';
import { Card, Drawer, Descriptions, Table, Button, Tag, Space, message, Typography, Tooltip } from 'antd';
import { EyeOutlined, DownloadOutlined, ReloadOutlined, FileTextOutlined } from '@ant-design/icons';
import request from '@/services/request';
import { getCurrentProjectId, getCurrentProjectName, PROJECT_CHANGED } from '@/pages/product/projectStore';
import { fetchProjectUnderstanding, openProjectAgent } from '@/services/projectExplorer';
import '../shell/shell.css';

const { Title } = Typography;

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

export default function ReportListPage() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [projectName, setProjectName] = useState(getCurrentProjectName());
  const [detail, setDetail] = useState<any | null>(null);
  const [showReport, setShowReport] = useState(false);
  const [pane, setPane] = useState<'overview' | 'risk' | 'coverage' | 'history'>('overview');
  const [coverage, setCoverage] = useState<any>(null);

  const fetchData = useCallback(async (p: number, ps: number) => {
    setLoading(true);
    try {
      const res: any = await request.get('/executions/list', {
        params: { page: p, page_size: ps, project_id: getCurrentProjectId() || undefined },
      });
      const d = res.data || res;
      // 只显示已完成的执行
      const completed = (d?.items || []).filter((item: any) =>
        item.status === 'success' || item.status === 'failed' || item.status === 'cancelled'
      );
      setData(completed);
      setTotal(completed.length);
    } catch {
      message.error('加载报告列表失败');
      setData([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(page, pageSize); }, [page, pageSize, fetchData]);
  useEffect(() => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    fetchProjectUnderstanding(projectId).then((data) => setCoverage(data?.coverage || null)).catch(() => setCoverage(null));
  }, [projectName]);
  useEffect(() => {
    const reload = () => {
      setProjectName(getCurrentProjectName());
      fetchData(1, pageSize);
    };
    window.addEventListener(PROJECT_CHANGED, reload);
    return () => window.removeEventListener(PROJECT_CHANGED, reload);
  }, [fetchData, pageSize]);

  // 统计数据
  const passedCount = data.filter((d) => d.status === 'success').length;
  const failedCount = data.filter((d) => d.status === 'failed').length;
  const passRate = data.length > 0 ? Math.round((passedCount / data.length) * 1000) / 10 : 0;

  return (
    <div className="pw-page">
      <div className="pw-head">
        <div>
          <h1>测试报告</h1>
          <p>用当前项目{projectName ? `「${projectName}」` : ''}已完成的执行记录做结论，不编造报告。</p>
        </div>
        <Button onClick={() => openProjectAgent('总结本次测试风险')}>✦ 总结本次测试风险</Button>
      </div>
      <div className="sub-tabs">
        <button type="button" className={pane === 'overview' ? 'is-on' : ''} onClick={() => setPane('overview')}>报告概览</button>
        <button type="button" className={pane === 'risk' ? 'is-on' : ''} onClick={() => setPane('risk')}>风险分析</button>
        <button type="button" className={pane === 'coverage' ? 'is-on' : ''} onClick={() => setPane('coverage')}>覆盖率</button>
        <button type="button" className={pane === 'history' ? 'is-on' : ''} onClick={() => setPane('history')}>历史报告</button>
      </div>
      {pane === 'coverage' ? (
        <div className="uw-panel" style={{ marginBottom: 16 }}>
          {coverage ? <p>覆盖率 {coverage.rate ?? coverage.score ?? '-'}{coverage.rate != null || coverage.score != null ? '%' : ''}。{coverage.advice || ''}</p> : <p>当前项目还没有覆盖率数据。</p>}
        </div>
      ) : null}
      {pane === 'risk' ? (
        <div className="uw-panel" style={{ marginBottom: 16 }}>
          <p>失败执行 {failedCount} 份。{failedCount ? '从下方历史报告里打开失败记录查看详情。' : '这一页没有失败报告。'}</p>
        </div>
      ) : null}
      {pane === 'overview' ? (
        <div className="uw-panel" style={{ marginBottom: 16 }}>
          <p>执行记录 {data.length} · 通过率 {passRate}% · 失败 {failedCount} · 高风险 {failedCount}{coverage ? ` · 覆盖率 ${coverage.rate ?? coverage.score ?? '-'}${coverage.rate != null || coverage.score != null ? '%' : ''}` : ''}</p>
        </div>
      ) : null}

      <Card
        title={<Title level={4} style={{ margin: 0 }}><FileTextOutlined /> 历史报告</Title>}
        extra={<Button icon={<ReloadOutlined />} onClick={() => fetchData(page, pageSize)}>刷新</Button>}
      >
        <Table
          dataSource={data}
          rowKey="id"
          loading={loading}
          size="middle"
          scroll={{ x: 1200 }}
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
            { title: '任务名称', dataIndex: 'task_name', width: 160, ellipsis: true,
              render: (name: string, r: any) => name || r.requirement || r.task_id || '-',
            },
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
            { title: 'AI分析', width: 90,
              render: (_: any, r: any) => hasAIAnalysis(r) ? <Tag color="geekblue">AI分析</Tag> : <Tag>无</Tag>,
            },
            { title: '结果', dataIndex: 'status', width: 100,
              render: (s: string) => {
                const map: Record<string, { color: string; text: string }> = {
                  success: { color: 'green', text: '通过' },
                  failed: { color: 'red', text: '失败' },
                  cancelled: { color: 'default', text: '已取消' },
                };
                const info = map[s] || { color: 'default', text: s };
                return <Tag color={info.color}>{info.text}</Tag>;
              },
            },
            { title: '通过/失败', width: 130,
              render: (_, r: any) => (
                <Space size={4}>
                  <Tag color="green">{r.success_count || 0}</Tag>
                  <Tag color="red">{r.failed_count || 0}</Tag>
                </Space>
              ),
            },
            { title: '耗时', dataIndex: 'duration', width: 110,
              render: (d: number) => formatDuration(d),
            },
            { title: '执行时间', dataIndex: 'start_time', width: 180, render: (t: string) => t || '-' },
            { title: '操作', width: 200, fixed: 'right' as const,
              render: (_: any, r: any) => (
                <Space>
                  <Tooltip title="查看详情">
                    <Button size="small" type="link" icon={<EyeOutlined />} onClick={() => { setDetail(r); setShowReport(false); }}>详情</Button>
                  </Tooltip>
                  <Tooltip title="查看HTML报告">
                    <Button size="small" icon={<FileTextOutlined />} onClick={() => { setDetail(r); setShowReport(true); }} />
                  </Tooltip>
                  <Tooltip title="下载Excel">
                    <Button size="small" icon={<DownloadOutlined />} onClick={() => {
                      const link = document.createElement('a');
                      link.href = `/api/executions/${r.id}/report?format=excel`;
                      link.download = `execution-${r.id}.xlsx`;
                      link.click();
                    }} />
                  </Tooltip>
                </Space>
              ),
            },
          ]}
        />
      </Card>
      <Drawer
        title={detail ? `报告 #${detail.id}` : '测试报告'}
        open={!!detail}
        onClose={() => { setDetail(null); setShowReport(false); }}
        width={720}
      >
        {detail ? (
          showReport ? (
            <iframe
              title={`测试报告 ${detail.id}`}
              src={`/api/executions/${detail.id}/report?format=html`}
              style={{ width: '100%', height: '70vh', border: '1px solid #d0d7de' }}
            />
          ) : (
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="任务">{detail.task_name || detail.requirement || detail.task_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="结果">{detail.status || '-'}</Descriptions.Item>
              <Descriptions.Item label="类型">{detail.execution_type || '-'}</Descriptions.Item>
              <Descriptions.Item label="通过">{detail.success_count ?? 0}</Descriptions.Item>
              <Descriptions.Item label="失败">{detail.failed_count ?? 0}</Descriptions.Item>
              <Descriptions.Item label="耗时">{formatDuration(detail.duration)}</Descriptions.Item>
              <Descriptions.Item label="执行时间">{detail.start_time || '-'}</Descriptions.Item>
              <Descriptions.Item label="AI 分析">{hasAIAnalysis(detail) ? '有' : '无'}</Descriptions.Item>
              {detail.analysis_result ? (
                <Descriptions.Item label="分析结果">
                  <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                    {typeof detail.analysis_result === 'string' ? detail.analysis_result : JSON.stringify(detail.analysis_result, null, 2)}
                  </pre>
                </Descriptions.Item>
              ) : null}
            </Descriptions>
          )
        ) : null}
      </Drawer>
    </div>
  );
}
