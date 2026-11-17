# Web / H5 目录规范

两棵目录树都是分类案例，其中的 `checkout`、`order`、`order-summary`、`apply-coupon` 不作为新建目录。

## 传统分层

适用于以页面和几个主要业务为主的项目。Vue 可统一将 `hooks/` 命名为 `composables/`。路由入口服从实际框架约定。

```text
web/
├── src/
│   ├── app/                      # 应用入口、路由、全局样式
│   ├── pages/checkout/           # 页面与该页面专属 UI
│   ├── api/order.ts              # 订单接口
│   ├── api/client.ts             # HTTP 封装
│   ├── components/               # 跨页面展示组件
│   ├── store/                    # 全局共享状态
│   └── hooks/                    # 跨页面有状态逻辑
└── tests/
```

## Feature-Sliced Design

切片默认通过公开入口依赖更低层的切片。页面私有代码留在页面切片内，各层按实际需要创建。[FSD 层与依赖规则](https://feature-sliced.design/docs/reference/layers)

```text
web/src/
├── app/                          # 启动、路由、Provider
├── pages/checkout/               # 页面组装
├── widgets/order-summary/        # 页面区块
├── features/apply-coupon/
│   ├── index.ts                  # 公开入口
│   ├── ui/
│   ├── model/
│   └── api/
├── entities/order/               # 订单模型及相关 UI
└── shared/
    ├── api/
    ├── ui/
    └── lib/
```
