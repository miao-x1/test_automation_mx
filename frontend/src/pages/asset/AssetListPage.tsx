import { useState, useEffect, useCallback } from 'react';
import { Card, Table, Button, Input, Tag, Space, message, Typography, Row, Col, Statistic } from 'antd';
import { PlusOutlined, ReloadOutlined, FileTextOutlined, CheckCircleOutlined, ClockCircleOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import request from '@/services/request';

const { Title } = Typography;

export default function AssetListPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keyword, setKeyword] = useState('');
  const [stats, setStats] = useState({ total: 0, published: 0, draft: 0 });

  const fetchData = useCallback(async (p: number, ps: number, kw: string) => {
    setLoading(true);
    try {
      const res: any = await request.get('/assets/v2/list', {
        params: { page: p, page_size: ps, keyword: kw.trim() || undefined },
      });
      const d = res.data || res;
      const items = d?.items || [];
      setData(items);
      setTotal(d?.total || items.length);

      try {
        const sRes: any = await request.get('/assets/v2/stats/summary');
        const sd = sRes.data || sRes;
        if (sd) {
          setStats({
            total: sd.total ?? items.length,
            published: sd.published || 0,
            draft: sd.draft || 0,
          });
        }
      } catch {
        setStats({ total: items.length, published: 0, draft: 0 });
      }
    } catch {
      message.error('加载资产列表失败');
      setData([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(page, pageSize, keyword); }, [page, pageSize, fetchData]);

  const statusMap: Record<string, { color: string; text: string }> = {
    draft: { color: 'orange', text: '草稿' },
    published: { color: 'green', text: '已发布' },
    review: { color: 'blue', text: '审核中' },
    archived: { color: 'default', text: '已归档' },
  };

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}><Card><Statistic title="资产总数" value={stats.total} prefix={<FileTextOutlined />} /></Card></Col>
        <Col span={8}><Card><Statistic title="已发布" value={stats.published} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#3d5a45' }} /></Card></Col>
        <Col span={8}><Card><Statistic title="草稿" value={stats.draft} prefix={<ClockCircleOutlined />} valueStyle={{ color: '#8a7348' }} /></Card></Col>
      </Row>

      <Card
        title={<Title level={4} style={{ margin: 0 }}>测试资产</Title>}
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/task/create')}>
            新建测试
          </Button>
        }
      >
        <Space style={{ marginBottom: 16 }}>
          <Input.Search
            placeholder="搜索资产名称"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={() => { setPage(1); fetchData(1, pageSize, keyword); }}
            style={{ width: 300 }}
            allowClear
          />
          <Button icon={<ReloadOutlined />} onClick={() => fetchData(page, pageSize, keyword)}>刷新</Button>
        </Space>

        <Table
          dataSource={data}
          rowKey="id"
          loading={loading}
          size="middle"
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
            { title: '资产名称', dataIndex: 'title', ellipsis: true },
            { title: '类型', dataIndex: 'asset_type', width: 100,
              render: (t: string) => {
                const map: Record<string, string> = { web: 'Web', api: 'API', android: 'Android', suite: '套件' };
                return <Tag>{map[t] || t}</Tag>;
              },
            },
            { title: '状态', dataIndex: 'status', width: 100,
              render: (s: string) => {
                const info = statusMap[s] || { color: 'default', text: s };
                return <Tag color={info.color}>{info.text}</Tag>;
              },
            },
            { title: '创建时间', dataIndex: 'created_at', width: 180, render: (t: string) => t || '-' },
            { title: '操作', width: 120, render: (_: any, r: any) => (
              <Button type="link" size="small" onClick={() => navigate(`/asset/generate?id=${r.id}`)}>编辑</Button>
            )},
          ]}
        />
      </Card>
    </div>
  );
}
