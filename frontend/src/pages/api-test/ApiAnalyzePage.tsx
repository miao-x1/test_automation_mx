import { useState, useCallback } from 'react';
import { Card, Table, Tag, Button, Space, Input, Descriptions, Drawer, Badge, message } from 'antd';
import { SearchOutlined, EditOutlined, CheckCircleOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';

interface ApiItem {
  name: string;
  method: string;
  path: string;
  headers: Record<string, string>;
  request_schema: Record<string, any>;
  response_schema: Record<string, any>;
  depends: string[];
  priority: string;
}

const methodColors: Record<string, string> = {
  GET: 'green',
  POST: 'blue',
  PUT: 'orange',
  DELETE: 'red',
  PATCH: 'purple',
};

export default function ApiAnalyzePage() {
  const [sessionId, setSessionId] = useState('');
  const [apis, setApis] = useState<ApiItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [detailApi, setDetailApi] = useState<ApiItem | null>(null);
  const [drawerVisible, setDrawerVisible] = useState(false);

  const fetchApis = useCallback(async () => {
    const id = parseInt(sessionId);
    if (!id) { message.warning('请输入会话ID'); return; }
    setLoading(true);
    try {
      const res = await fetch(`/api/workflow/result?session_id=${id}&agent=APIExtraction`, { credentials: 'include' });
      const data = await res.json();
      const d = data.data || data;
      const output = typeof d.output === 'string' ? JSON.parse(d.output) : d.output;
      setApis(output?.apis || []);
      message.success(`加载 ${output?.apis?.length || 0} 个API`);
    } catch (e: any) {
      message.error(e?.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  const handleConfirm = async () => {
    const id = parseInt(sessionId);
    if (!id) return;
    try {
      await fetch(`/api/knowledge/cases/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ session_id: id, use_rag: true }),
      });
      message.success('已确认API，开始生成用例');
    } catch { message.error('操作失败'); }
  };

  const columns: ColumnsType<ApiItem> = [
    { title: '接口名', dataIndex: 'name', width: 160, ellipsis: true },
    { title: '方法', dataIndex: 'method', width: 80, render: (v: string) => <Tag color={methodColors[v] || 'default'}>{v}</Tag> },
    { title: '路径', dataIndex: 'path', ellipsis: true },
    { title: '优先级', dataIndex: 'priority', width: 70, render: (v: string) => <Tag color={v === 'P0' ? 'red' : v === 'P1' ? 'orange' : 'blue'}>{v}</Tag> },
    { title: '依赖', dataIndex: 'depends', width: 120, render: (v: string[]) => v?.length > 0 ? v.map(d => <Tag key={d}>{d}</Tag>) : '-' },
    { title: '操作', width: 80, render: (_: any, r: ApiItem) => (
      <Button size="small" type="link" icon={<EditOutlined />} onClick={() => { setDetailApi(r); setDrawerVisible(true); }}>详情</Button>
    )},
  ];

  return (
    <div>
      <Card title="接口解析结果" size="small" extra={
        <Space>
          <Input placeholder="输入会话ID" value={sessionId} onChange={e => setSessionId(e.target.value)} style={{ width: 140 }} onPressEnter={fetchApis} />
          <Button icon={<SearchOutlined />} onClick={fetchApis} loading={loading}>加载</Button>
          {apis.length > 0 && (
            <Button type="primary" icon={<CheckCircleOutlined />} onClick={handleConfirm}>确认并生成用例</Button>
          )}
        </Space>
      }>
        <div style={{ marginBottom: 12 }}>
          <Space>
            <Badge count={apis.length} /> <span>个API接口</span>
          </Space>
        </div>
        <Table dataSource={apis} columns={columns} rowKey="name" loading={loading} size="small" pagination={false} />
      </Card>

      <Drawer title={detailApi?.name || 'API详情'} placement="right" width={600} open={drawerVisible} onClose={() => setDrawerVisible(false)}>
        {detailApi && (
          <div>
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="方法"><Tag color={methodColors[detailApi.method]}>{detailApi.method}</Tag></Descriptions.Item>
              <Descriptions.Item label="路径">{detailApi.path}</Descriptions.Item>
              <Descriptions.Item label="优先级"><Tag color={detailApi.priority === 'P0' ? 'red' : 'orange'}>{detailApi.priority}</Tag></Descriptions.Item>
              <Descriptions.Item label="依赖">{detailApi.depends?.join(', ') || '无'}</Descriptions.Item>
            </Descriptions>
            <Card title="请求头" size="small" style={{ marginTop: 16 }}>
              <pre style={{ margin: 0, fontSize: 12 }}>{JSON.stringify(detailApi.headers || {}, null, 2)}</pre>
            </Card>
            <Card title="请求体 Schema" size="small" style={{ marginTop: 16 }}>
              <pre style={{ margin: 0, fontSize: 12 }}>{JSON.stringify(detailApi.request_schema || {}, null, 2)}</pre>
            </Card>
            <Card title="响应体 Schema" size="small" style={{ marginTop: 16 }}>
              <pre style={{ margin: 0, fontSize: 12 }}>{JSON.stringify(detailApi.response_schema || {}, null, 2)}</pre>
            </Card>
          </div>
        )}
      </Drawer>
    </div>
  );
}
