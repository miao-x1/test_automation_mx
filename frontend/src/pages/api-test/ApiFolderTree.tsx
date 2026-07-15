/**
 * API 测试 - 目录树组件
 * 支持新建/删除目录、选中过滤、显示用例数量
 */
import { useState, useEffect, useCallback } from 'react';
import { Tree, Card, Button, Modal, Input, message, Space, Popconfirm } from 'antd';
import {
  FolderOutlined, FolderAddOutlined, DeleteOutlined, ReloadOutlined,
} from '@ant-design/icons';
import { getFolderTree, saveFolder, deleteFolder, ApiCaseFolder } from '../../services/apiCase';

interface TreeNodeType {
  title: React.ReactNode;
  key: string;
  icon: React.ReactNode;
  children?: TreeNodeType[];
}

interface ApiFolderTreeProps {
  onSelect?: (folderId?: number) => void;
  selectedFolder?: number;
}

function buildFolderNodes(folders: ApiCaseFolder[], onDelete: (id: number) => void): TreeNodeType[] {
  return folders.map(f => ({
    title: (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        {f.name} <span style={{ color: '#999', fontSize: 12 }}>({f.case_count})</span>
        <Popconfirm
          title="确认删除该目录？"
          onConfirm={(e) => { e?.stopPropagation(); onDelete(f.id); }}
          onCancel={(e) => e?.stopPropagation()}
        >
          <DeleteOutlined
            style={{ color: '#ff4d4f', fontSize: 12 }}
            onClick={(e) => e.stopPropagation()}
          />
        </Popconfirm>
      </span>
    ),
    key: String(f.id),
    icon: <FolderOutlined />,
    children: f.children ? buildFolderNodes(f.children, onDelete) : [],
  }));
}

export default function ApiFolderTree({ onSelect, selectedFolder }: ApiFolderTreeProps) {
  const [folders, setFolders] = useState<ApiCaseFolder[]>([]);
  const [treeData, setTreeData] = useState<TreeNodeType[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchFolders = useCallback(async () => {
    setLoading(true);
    try {
      const tree = await getFolderTree();
      setFolders(tree);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetchFolders(); }, [fetchFolders]);

  const handleDeleteFolder = useCallback(async (id: number) => {
    try {
      await deleteFolder(id);
      message.success('目录已删除');
      fetchFolders();
    } catch {
      message.error('删除目录失败');
    }
  }, [fetchFolders]);

  useEffect(() => {
    const nodes = buildFolderNodes(folders, handleDeleteFolder);
    setTreeData([
      { title: '全部用例', key: 'all', icon: <FolderOutlined />, children: nodes },
    ]);
  }, [folders, handleDeleteFolder]);

  const handleNewFolder = () => {
    Modal.confirm({
      title: '新建目录',
      content: <Input id="folder-name-input" placeholder="目录名称" />,
      onOk: async () => {
        const input = document.getElementById('folder-name-input') as HTMLInputElement;
        const name = input?.value?.trim();
        if (!name) { message.warning('目录名不能为空'); return; }
        try {
          await saveFolder({ name });
          message.success('目录创建成功');
          fetchFolders();
        } catch { message.error('创建失败'); }
      },
    });
  };

  const handleSelect = (_selectedKeys: React.Key[], info: { node: { key: string | number } }) => {
    const key = info.node.key as string;
    if (key === 'all') {
      onSelect?.(undefined);
    } else {
      onSelect?.(Number(key));
    }
  };

  return (
    <Card
      title="目录"
      size="small"
      style={{ width: 260, flexShrink: 0 }}
      extra={
        <Space>
          <Button size="small" icon={<ReloadOutlined />} onClick={fetchFolders} loading={loading} />
          <Button size="small" icon={<FolderAddOutlined />} onClick={handleNewFolder} />
        </Space>
      }
    >
      <Tree
        treeData={treeData}
        defaultExpandAll
        showIcon
        selectedKeys={selectedFolder ? [String(selectedFolder)] : ['all']}
        onSelect={handleSelect}
      />
    </Card>
  );
}
