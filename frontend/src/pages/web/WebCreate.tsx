/**
 * Web - 测试设计
 *
 * 统一入口：需求驱动 + 脚本上传
 */
import { Card, Tabs } from 'antd';
import { PlusOutlined, UploadOutlined } from '@ant-design/icons';
import RequirementCenter from '../RequirementCenter';
import ScriptUploadPage from '../ScriptUploadPage';
import { PageHeader } from '../../components/UI';

export default function WebCreate() {
  return (
    <div>
      <PageHeader title="测试设计" subtitle="通过需求或上传脚本设计Web测试" icon={<PlusOutlined />} />
      <Card>
        <Tabs items={[
          {
            key: 'requirement',
            label: '需求驱动',
            icon: <PlusOutlined />,
            children: <RequirementCenter />,
          },
          {
            key: 'script',
            label: '脚本上传',
            icon: <UploadOutlined />,
            children: <ScriptUploadPage />,
          },
        ]} />
      </Card>
    </div>
  );
}
