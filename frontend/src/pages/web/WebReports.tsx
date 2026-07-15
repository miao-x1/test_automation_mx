/**
 * Web - 测试报告
 *
 * 展示测试报告列表
 */
import { useState, useEffect, useCallback } from 'react';
import { Card, Table, Tag, Space, Button, message } from 'antd';
import { FileTextOutlined, ReloadOutlined, EyeOutlined } from '@ant-design/icons';
import request from '../../services/request';
import { PageHeader } from '../../components/UI';

interface ReportItem {
  id: number;
  task_id: number;
  task_name: string;
  status: string;
  duration: number | null;
  report_path: string | null;
  created_at: string;
}

export default function WebReports() {
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);

  const fetchReports = useCallback(async () => {
    setLoading(true);
    try {
      const res: any = await request.get('/executions/list', {
        params: { page, page_size: 20, status: 'success' },
      });
      const data = res?.data || res;
      setReports(data?.items || []);
      setTotal(data?.total || 0);
    } catch (e) {
      console.error('[WebReports] fetchReports failed:', e);
      message.error('加载报告列表失败');
      setReports([]);
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => { fetchReports(); }, [fetchReports]);

  const handleViewReport = (record: ReportItem) => {
    if (record.report_path) {
      window.open(`/api/executions/${record.id}/report`, '_blank');
    } else {
      message.info('该执行记录暂无报告');
    }
  };

  return (
    <div>
      <PageHeader title="测试报告" subtitle="查看已完成的测试报告" icon={<FileTextOutlined />} />
      <Card>
        <Space style={{ marginBottom: 16 }}>
          <Button icon={<ReloadOutlined />} onClick={fetchReports}>刷新</Button>
        </Space>
        <Table
          dataSource={reports}
          rowKey="id"
          loading={loading}
          pagination={{ current: page, total, pageSize: 20, onChange: setPage }}
          columns={[
            { title: '执行ID', dataIndex: 'id', width: 80 },
            { title: '任务名称', dataIndex: 'task_name', ellipsis: true },
            { title: '状态', dataIndex: 'status', width: 80, render: (s: string) => <Tag color="green">{s}</Tag> },
            { title: '耗时', dataIndex: 'duration', width: 80, render: (d: number) => d ? `${d.toFixed(1)}s` : '-' },
            { title: '创建时间', dataIndex: 'created_at', width: 160 },
            {
              title: '操作', width: 100,
              render: (_: any, r: ReportItem) => (
                <Button size="small" icon={<EyeOutlined />} onClick={() => handleViewReport(r)} disabled={!r.report_path}>
                  查看报告
                </Button>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
