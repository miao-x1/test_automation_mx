import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button, Empty, Input, Select, Table } from 'antd';
import { getCurrentProjectId } from '@/pages/product/projectStore';
import { fetchProjectFile } from '@/services/projectExplorer';
import { buildFileTree, coverageTone, matchKeyword } from './understanding';
import { useUnderstanding } from './UnderstandLayout';
import { filePreviewBody } from './filePreview';

function Crumb({ items }: { items: Array<{ label: string; onBack?: () => void }> }) {
  return (
    <div className="uw-crumb">
      项目理解
      {items.map((item) => (
        <span key={item.label}>
          {' / '}
          {item.onBack ? <button type="button" onClick={item.onBack}>{item.label}</button> : item.label}
        </span>
      ))}
    </div>
  );
}

function Head({ title, desc, extra }: { title: string; desc?: string; extra?: any }) {
  return (
    <div className="uw-pagehead">
      <div>
        <h2>{title}</h2>
        {desc ? <p>{desc}</p> : null}
      </div>
      {extra}
    </div>
  );
}

export function OverviewSection() {
  const { data, openDrawer } = useUnderstanding();
  if (!data?.imported) {
    return <div className="uw-panel"><Empty description="先导入项目。导入后这里只展示真实解析结果。" /></div>;
  }
  const project = data.project || {};
  const scale = data.scale || {};
  return (
    <>
      <div className="uw-pagehead">
        <div>
          <h2>项目理解</h2>
          <p>帮助你理解当前项目的结构、功能和代码</p>
        </div>
      </div>
      <div className="uw-panel uw-summary">
        <h1>{project.name || '当前项目'}</h1>
        <p>{project.description}</p>
        <p>技术栈：{(project.stack || []).join(' · ') || '-'}</p>
      </div>
      <div className="uw-stats uw-stats-4">
        {[
          ['页面', scale.pages],
          ['功能', scale.features ?? (data.features || []).length],
          ['API', scale.apis],
          ['代码文件', scale.files],
        ].map(([label, value]) => (
          <div key={String(label)} className="uw-stat">
            <b>{value ?? 0}</b><span>{label}</span>
          </div>
        ))}
      </div>
      <div className="uw-60-40">
        <div className="uw-panel">
          <h3>项目架构</h3>
          <div className="uw-arch">
            {(data.architecture || []).map((node: any, index: number) => (
              <div key={node.id}>
                <button className="uw-node" type="button" onClick={() => openDrawer(node.name, <p>{node.detail || '该层来自当前项目解析。'}</p>)}>
                  <b>{node.name}</b>
                  <small>{node.detail}</small>
                </button>
                {index < (data.architecture || []).length - 1 ? <div className="uw-arrow">↓</div> : null}
              </div>
            ))}
          </div>
        </div>
        <div className="uw-panel">
          <h3>核心模块</h3>
          {(data.modules || []).map((item: any) => (
            <div key={item.id} className="uw-mod" onClick={() => openDrawer(item.name, (
              <div>
                <p>{item.duty || '-'}</p>
                <p>功能 {item.feature_count || 0}　页面 {item.page_count || 0}　API {item.api_count || 0}</p>
                <p>{(item.features || []).join(' / ') || ''}</p>
              </div>
            ))}>
              <span>{item.name}</span>
              <span className="uw-tone-empty">{item.feature_count || 0} 功能</span>
            </div>
          ))}
        </div>
      </div>
      <div className="uw-2">
        <div className="uw-panel">
          <h3>核心功能</h3>
          {(data.features || []).map((item: any) => (
            <div key={item.id} className="uw-mod" onClick={() => openDrawer(item.name, (
              <div>
                <p>{item.description || '-'}</p>
                <p>页面 {item.entry_page || '-'}</p>
                <p>覆盖 {item.coverage?.rate || 0}%</p>
              </div>
            ))}>
              <span>{item.name}</span>
              <span className={`uw-tone-${coverageTone(item.coverage?.rate || 0)}`}>{item.coverage?.rate || 0}%</span>
            </div>
          ))}
        </div>
        <div className="uw-panel">
          <h3>最近发现</h3>
          <p>{(data.features || []).map((item: any) => item.name).filter(Boolean).join(' / ') || '还没有识别到功能'}</p>
        </div>
      </div>
    </>
  );
}

export function PagesSection() {
  const { data, ask, openDrawer } = useUnderstanding();
  const [params, setParams] = useSearchParams();
  const [keyword, setKeyword] = useState('');
  const [module, setModule] = useState<string>();
  const pages = (data?.pages || []).filter((item: any) => matchKeyword(item, keyword) && (!module || item.module === module));
  const current = pages.find((item: any) => item.id === params.get('id'));
  const modules = [...new Set((data?.pages || []).map((item: any) => item.module).filter(Boolean))];

  if (current) {
    return (
      <>
        <Crumb items={[{ label: '页面', onBack: () => setParams({}) }, { label: current.name }]} />
        <Head title={current.name} desc={current.route} extra={<Button onClick={() => ask(`${current.name} 页面是做什么的？相关测试怎么补？`)}>解释页面</Button>} />
        <div className="uw-2">
          <div className="uw-panel">
            <h3>页面信息</h3>
            <p>页面文件　<button type="button" className="uw-crumb" onClick={() => current.path && filePreviewBody(current.path).then((body) => openDrawer(current.path, body))}>{current.path}</button></p>
            <p>模块　{current.module}</p>
            <p>元素　{current.element_count || 0}</p>
          </div>
          <div className="uw-panel">
            <h3>AI 理解</h3>
            <p>{current.purpose}</p>
          </div>
        </div>
        <div className="uw-panel uw-table">
          <h3>页面元素</h3>
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={current.elements || []}
            onRow={(row) => ({ onClick: () => openDrawer(row.name, (
              <div>
                <p>类型　{row.type}</p>
                <p>文件　{row.path}:{row.line || '-'}</p>
                <p>事件　{row.handler || '-'}</p>
                <p>定位　{row.locator || '-'}</p>
                <Button size="small" onClick={() => ask(`解释元素 ${row.name}，它调用什么？`)}>AI解释</Button>
              </div>
            )) })}
            columns={[
              { title: '元素', dataIndex: 'name' },
              { title: '类型', dataIndex: 'type', width: 90 },
              { title: '文件', dataIndex: 'path' },
              { title: '定位', render: () => <span className="uw-tone-ok">✓</span>, width: 60 },
            ]}
          />
        </div>
      </>
    );
  }

  return (
    <>
      <Head title="页面" desc={`项目中识别到 ${pages.length} 个页面`} extra={(
        <div style={{ display: 'flex', gap: 8 }}>
          <Input.Search allowClear placeholder="搜索页面" onSearch={setKeyword} style={{ width: 200 }} />
          <Select allowClear placeholder="模块" style={{ width: 140 }} value={module} onChange={setModule} options={modules.map((item) => ({ value: item, label: item }))} />
        </div>
      )} />
      <div className="uw-panel uw-table">
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={pages}
          onRow={(row) => ({ onClick: () => setParams({ id: row.id }) })}
          columns={[
            { title: '页面', dataIndex: 'name' },
            { title: 'URL', dataIndex: 'route' },
            { title: '模块', dataIndex: 'module', width: 120 },
            { title: '元素', dataIndex: 'element_count', width: 70 },
            { title: '测试', render: (_: any, row: any) => (row.cases || []).length, width: 70 },
          ]}
        />
        {!pages.length ? <div className="uw-empty">没有识别到页面</div> : null}
      </div>
    </>
  );
}

export function FeaturesSection() {
  const { data, ask, openDrawer } = useUnderstanding();
  const [params, setParams] = useSearchParams();
  const [keyword, setKeyword] = useState('');
  const features = (data?.features || []).filter((item: any) => matchKeyword(item, keyword));
  const current = features.find((item: any) => item.id === params.get('id'));

  if (current) {
    return (
      <>
        <Crumb items={[{ label: '功能', onBack: () => setParams({}) }, { label: current.name }]} />
        <Head title={current.name} />
        <div className="uw-3">
          <div className="uw-panel">
            <h3>功能信息</h3>
            <p>{current.description}</p>
            <p>模块：{current.module}</p>
            <p>页面：{current.entry_page || '-'}</p>
            <p>已有测试：{(current.cases || []).length}</p>
          </div>
          <div className="uw-panel">
            <h3>执行链路</h3>
            <div className="uw-chain">
              {(current.chain || []).map((item: any) => (
                <button key={`${item.layer}-${item.name}`} type="button" onClick={() => item.path && filePreviewBody(item.path).then((body) => openDrawer(item.path, body))}>
                  <b>{item.layer}</b><div>{item.name}</div>
                </button>
              ))}
            </div>
          </div>
          <div className="uw-panel">
            <h3>关联信息</h3>
            <p>测试用例　{(current.cases || []).length}</p>
            <p>API　{(current.apis || []).length}</p>
            <p>文件　{(current.files || []).length}</p>
            <Button size="small" onClick={() => ask(`${current.name} 的完整实现链路是什么？`)}>查看调用链</Button>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <Head title="功能" desc={`${features.length} 个业务功能`} extra={<Input.Search allowClear placeholder="搜索功能" onSearch={setKeyword} style={{ width: 220 }} />} />
      <div className="uw-panel uw-table">
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={features}
          onRow={(row) => ({ onClick: () => setParams({ id: row.id }) })}
          columns={[
            { title: '功能', dataIndex: 'name' },
            { title: '模块', dataIndex: 'module', width: 100 },
            { title: '页面', dataIndex: 'entry_page', width: 140 },
            { title: '测试覆盖', render: (_: any, row: any) => <span className={`uw-tone-${coverageTone(row.coverage?.rate || 0)}`}>{row.coverage?.rate || 0}%</span>, width: 90 },
          ]}
        />
      </div>
    </>
  );
}

export function ModulesSection() {
  const { data, openDrawer } = useUnderstanding();
  const [params, setParams] = useSearchParams();
  const modules = data?.modules || [];
  const current = modules.find((item: any) => item.id === params.get('id')) || modules[0];
  return (
    <div className="uw-split">
      <div className="uw-panel">
        <h3>模块</h3>
        {modules.map((item: any) => (
          <div key={item.id} className="uw-mod" onClick={() => setParams({ id: item.id })}>
            <span>{item.name}{current?.id === item.id ? ' ←' : ''}</span>
          </div>
        ))}
      </div>
      {current ? (
        <div className="uw-panel">
          <Crumb items={[{ label: '模块' }, { label: current.name }]} />
          <h2 style={{ marginTop: 0 }}>{current.name}</h2>
          <p>{current.duty}</p>
          <p>页面：{current.page_count}　功能：{current.feature_count}　API：{current.api_count}</p>
          <h3>核心功能</h3>
          <p>{(current.features || []).join(' / ') || '-'}</p>
          {(current.files || []).map((path: string) => (
            <div key={path}>
              <button type="button" className="uw-crumb" onClick={() => filePreviewBody(path).then((body) => openDrawer(path, body))}>{path}</button>
            </div>
          ))}
        </div>
      ) : <Empty description="没有识别到模块" />}
    </div>
  );
}

export function ApisSection() {
  const { data, openDrawer } = useUnderstanding();
  const [params, setParams] = useSearchParams();
  const [keyword, setKeyword] = useState('');
  const [method, setMethod] = useState<string>();
  const apis = (data?.apis || []).filter((item: any) => matchKeyword(item, keyword) && (!method || item.method === method));
  const current = apis.find((item: any) => item.id === params.get('id'));

  if (current) {
    return (
      <>
        <Crumb items={[{ label: '接口', onBack: () => setParams({}) }, { label: current.name }]} />
        <Head title={current.name} />
        <div className="uw-3">
          <div className="uw-panel">
            <h3>接口信息</h3>
            <p>{current.method} {current.path}</p>
            <p>功能　{current.feature}</p>
            <p>模块　{current.module}</p>
            <pre className="uw-code" style={{ height: 160 }}>{current.snippet || '暂无片段'}</pre>
          </div>
          <div className="uw-panel">
            <h3>调用关系</h3>
            <div className="uw-chain">
              {(current.callers || []).map((item: any) => <div key={`${item.path}-${item.name}`}>调用方　{item.name}</div>)}
              {current.controller ? <button type="button" onClick={() => current.file && filePreviewBody(current.file).then((body) => openDrawer(current.file, body))}>Controller　{current.controller}</button> : null}
              {current.service ? <button type="button" onClick={() => current.service_file && filePreviewBody(current.service_file).then((body) => openDrawer(current.service_file, body))}>Service　{current.service}</button> : null}
            </div>
          </div>
          <div className="uw-panel">
            <h3>相关测试</h3>
            <p>{current.coverage || 0} 个测试用例</p>
            {(current.cases || []).map((item: any) => <p key={item.id || item.name}>{item.name || item.case_name}</p>)}
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <Head title="API 接口" extra={(
        <div style={{ display: 'flex', gap: 8 }}>
          <Input.Search allowClear placeholder="搜索 API" onSearch={setKeyword} style={{ width: 200 }} />
          <Select allowClear placeholder="方法" style={{ width: 100 }} value={method} onChange={setMethod} options={['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((item) => ({ value: item, label: item }))} />
        </div>
      )} />
      <div className="uw-panel uw-table">
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={apis}
          onRow={(row) => ({ onClick: () => setParams({ id: row.id }) })}
          columns={[
            { title: 'Method', dataIndex: 'method', width: 80 },
            { title: 'Path', dataIndex: 'path' },
            { title: '功能', dataIndex: 'feature' },
            { title: '模块', dataIndex: 'module', width: 100 },
            { title: '调用次数', dataIndex: 'frontend_calls', width: 90 },
            { title: '测试', dataIndex: 'coverage', width: 70 },
          ]}
        />
      </div>
    </>
  );
}

function TreeNode({ node, depth, current, onPick }: { node: any; depth: number; current?: string; onPick: (path: string) => void }) {
  return (
    <div className="uw-tree" style={{ paddingLeft: depth * 10 }}>
      {Object.values(node.children || {}).map((child: any) => (
        <div key={child.name}>
          <div className="uw-tree-dir">{child.name}</div>
          <TreeNode node={child} depth={depth + 1} current={current} onPick={onPick} />
        </div>
      ))}
      {(node.files || []).map((file: any) => (
        <button key={file.path} className={file.path === current ? 'is-on' : ''} onClick={() => onPick(file.path)}>{file.name}</button>
      ))}
    </div>
  );
}

export function CodeSection() {
  const { data, ask, openDrawer } = useUnderstanding();
  const [params, setParams] = useSearchParams();
  const [content, setContent] = useState('');
  const files = data?.files || [];
  const current = files.find((item: any) => item.path === params.get('path')) || files[0];
  const tree = useMemo(() => buildFileTree(files), [files]);

  useEffect(() => {
    const projectId = getCurrentProjectId();
    if (!projectId || !current?.path) return;
    fetchProjectFile(projectId, current.path).then((row) => setContent(row?.content || current.snippet || '')).catch(() => setContent(current.snippet || ''));
  }, [current?.path]);

  return (
    <>
      <Crumb items={[{ label: '代码' }, ...(current ? [{ label: current.path }] : [])]} />
      <div className="uw-ide">
        <div className="uw-ide-pane">
          <h3>文件树</h3>
          <TreeNode node={tree} depth={0} current={current?.path} onPick={(path) => setParams({ path })} />
        </div>
        <div className="uw-ide-pane uw-ide-code">
          <pre className="uw-code">{content || '选择一个真实源码文件'}</pre>
        </div>
        <div className="uw-ide-pane">
          <h3>AI 理解</h3>
          <p>{current?.feature || '从索引读取的文件说明'}</p>
          <p>模块　{current?.module || '-'}</p>
          <p>规模　{current?.lines || 0} 行</p>
          <div style={{ display: 'grid', gap: 6 }}>
            {[
              ['解释文件', `解释 ${current?.path}，它和哪些页面、接口有关？`],
              ['解释函数', `解释 ${current?.path} 里的函数`],
              ['查找调用方', `${current?.path} 被谁调用？`],
              ['查找被调用方', `${current?.path} 调用了谁？`],
              ['查找相关功能', `${current?.path} 对应哪些功能？`],
              ['查找相关测试', `${current?.path} 有哪些相关测试？`],
              ['影响分析', `改 ${current?.path} 会影响哪些测试？`],
            ].map(([label, q]) => (
              <Button key={label} size="small" disabled={!current} onClick={() => ask(q)}>{label}</Button>
            ))}
            <Button size="small" disabled={!current} onClick={() => openDrawer(current?.name || '文件', <p>{current?.path}</p>)}>函数详情</Button>
          </div>
        </div>
      </div>
    </>
  );
}

export function FlowsSection() {
  const { data, openDrawer } = useUnderstanding();
  const flow = (data?.flows || [])[0];
  const [index, setIndex] = useState(0);
  const step = flow?.steps?.[index];
  return (
    <>
      <Head title="业务流程" desc={flow?.name} />
      <div className="uw-60-40">
        <div className="uw-panel">
          <div className="uw-flow">
            {(flow?.steps || []).map((item: any, i: number) => (
              <div key={item.name}>
                <button type="button" className={`uw-flow-step ${i === index ? 'is-on' : ''}`} onClick={() => setIndex(i)}>{item.name}</button>
                {i < (flow.steps || []).length - 1 ? <div className="uw-arrow">↓</div> : null}
              </div>
            ))}
          </div>
        </div>
        <div className="uw-panel">
          {step ? (
            <>
              <h3>步骤：{step.name}</h3>
              <p>页面：{step.page || '-'}</p>
              <p>元素：{(step.elements || []).join('、') || '-'}</p>
              <p>API：{(step.apis || []).join(' / ') || '-'}</p>
              <p>代码：{step.path ? (
                <button type="button" className="uw-crumb" onClick={() => filePreviewBody(step.path).then((body) => openDrawer(step.path, body))}>{step.path}</button>
              ) : '-'}</p>
            </>
          ) : <Empty description="没有识别到流程" />}
        </div>
      </div>
    </>
  );
}

export function CoverageSection() {
  const { data, ask } = useUnderstanding();
  const coverage = data?.coverage || {};
  const features = coverage.features || [];
  const current = features[0];
  const missing = Math.max((current?.total || 0) > 0 ? 0 : 1, 0);
  return (
    <>
      <Head title="测试关联" desc="项目理解对象最终要落到测试资产" />
      <div className="uw-panel">
        <div className="uw-map">
          <div>
            <b>项目理解对象</b>
            <ul>
              <li>页面</li>
              <li>功能</li>
              <li>API</li>
              <li>元素</li>
            </ul>
          </div>
          <div>─────→</div>
          <div>
            <b>测试资产</b>
            <ul>
              <li>测试用例</li>
              <li>测试场景</li>
              <li>测试数据</li>
              <li>自动化脚本</li>
            </ul>
          </div>
        </div>
      </div>
      {current ? (
        <div className="uw-panel">
          <h3>{current.name}</h3>
          <p>相关测试：{current.total || 0}</p>
          <p>已覆盖：{current.total || 0}</p>
          <p>未覆盖：{missing}</p>
          <p>风险：{current.rate >= 80 ? '低' : current.total ? '中' : '高'}</p>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button onClick={() => ask(`${current.name} 有没有测试完整？缺口是什么？`)}>分析测试缺口</Button>
            <Button type="primary" onClick={() => ask(`生成${current.name}缺失测试用例`)}>生成测试用例</Button>
          </div>
        </div>
      ) : null}
      <div className="uw-panel uw-table">
        <Table rowKey="name" size="small" pagination={false} dataSource={coverage.pages || []} columns={[
          { title: '页面', dataIndex: 'name' },
          { title: '相关用例', dataIndex: 'total' },
          { title: '已覆盖', dataIndex: 'covered' },
          { title: '未覆盖', dataIndex: 'missing' },
        ]} />
      </div>
    </>
  );
}
