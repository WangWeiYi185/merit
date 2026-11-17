# Node.js / NestJS 目录规范

每个业务模块声明自身依赖，并通过模块导出可供其他模块使用的服务。[NestJS 模块指南](https://docs.nestjs.com/modules)

```text
server/
├── src/
│   ├── main.ts
│   ├── app.module.ts
│   ├── modules/order/
│   │   ├── order.module.ts
│   │   ├── order.controller.ts
│   │   ├── order.service.ts
│   │   ├── order.repository.ts
│   │   └── dto/
│   └── common/                   # 跨模块守卫、过滤器
└── test/
```
