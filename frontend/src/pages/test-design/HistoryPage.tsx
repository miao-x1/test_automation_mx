import { useState, useEffect, useCallback } from 'react';
import { Table, Tag, Badge, Button, Space, Input, Select, message } from 'antd';
import { EyeOutlined, SearchOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { assetTypeConfig, statusConfig, sourceConfig, type AssetItem } from './constants';

interface Props {
  onDetail: (id: number) => void;
}

export default function HistoryPage({ onDetail }: Props) {
  const [items, setItems] = useState<AssetItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [filterType, setFilterType] = useState<string | undefined>();
  const [filterKeyword, setFilterKeyword] = useState('');

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        skip: String((page - 1) * pageSize),
        limit: String(pageSize),
      });
      // 历史页：已执行 + 失败
      params.set('status', 'executed');
      if (filterType) params.set('asset_type', filterType);
      if (filterKeyword) params.set('keyword', filterKeyword);

      const res = await fetch(`/api/assets/v2/list?${params}`, { credentials: 'include' });
      const data = await res.json();
      if (data.items) { setItems(data.items); setTotal(data.total); }
    } catch { message.error('加载失败'); }
    finally { setLoading(false); }
  }, [page, pageSize, filterType, filterKeyword]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const columns: ColumnsType<AssetItem> = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '标题', dataIndex: 'title', ellipsis: true },
    { title: '类型', dataIndex: 'asset_type', width: 100, render: (v: string) => <Tag color={assetTypeConfig[v]?.color || 'blue'}>{assetTypeConfig[v]?.label || v}</Tag> },
    { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => {
      const cfg = statusConfig[v] || statusConfig.failed;
      return <Badge status={cfg.badge} text={<span style={{ color: cfg.color }}>{cfg.label}</span>} />;
    }},
    { title: '来源', dataIndex: 'source_type', width: 80, render: (v: string) => <Tag color={sourceConfig[v]?.color || 'default'}>{sourceConfig[v]?.label || v}</Tag> },
    { title: '创建时间', dataIndex: 'created_at', width: 160 },
    { title: '操作', width: 80, render: (_: any, r: AssetItem) => <Button size="small" type="link" icon={<EyeOutlined />} onClick={() => onDetail(r.id)}>详情</Button> },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 12 }} wrap>
        <Input placeholder="关键词" prefix={<SearchOutlined />} value={filterKeyword} onChange={e => setFilterKeyword(e.target.value)} style={{ width: 180 }} allowClear />
        <Select placeholder="类型" value={filterType} onChange={setFilterType} allowClear style={{ width: 110 }}
          options={Object.entries(assetTypeConfig).map(([k, v]) => ({ value: k, label: v.label }))} />
        <Button icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>
      </Space>
      <Table
        dataSource={items} columns={columns} rowKey="id" loading={loading}
        pagination={{ current: page, pageSize, total, onChange: (p, ps) => { setPage(p); setPageSize(ps); }, showSizeChanger: true, showTotal: t => `共 ${t} 条` }}
        size="small"
      />
    </div>
  );
}
