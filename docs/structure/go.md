# Go 服务端 目录规范

下面的树是分类案例，其中的 `order` 不作为新建目录。可执行入口放在 `cmd/`，服务实现放在 `internal/`。需要维护对外契约时，可用 `api/` 存放接口定义。[Go 模块布局](https://go.dev/doc/modules/layout#server-project)

```text
server/
├── go.mod
├── cmd/api/main.go
├── internal/
│   ├── order/
│   │   ├── handler.go
│   │   ├── service.go
│   │   ├── repository.go
│   │   └── service_test.go
│   └── platform/database/
└── api/openapi.yaml
```
