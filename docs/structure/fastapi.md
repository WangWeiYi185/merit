# Python / FastAPI 目录规范

下面的树是分类案例，其中的 `order` 不作为新建目录。各业务包提供 `APIRouter`，由应用入口集中注册。[FastAPI 多文件应用](https://fastapi.tiangolo.com/tutorial/bigger-applications/)

```text
server/
├── pyproject.toml
├── app/
│   ├── main.py
│   ├── modules/order/
│   │   ├── router.py
│   │   ├── schemas.py
│   │   ├── service.py
│   │   └── repository.py
│   └── core/                     # 应用配置与通用基础设施
└── tests/modules/order/
```
