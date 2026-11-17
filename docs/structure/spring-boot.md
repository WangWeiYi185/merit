# Java / Spring Boot 目录规范

下面的树是分类案例，其中的 `shop`、`order` 不作为新建目录。应用启动类放在业务包的上层。控制器处理接入与 DTO，服务编排用例和事务，领域包承载业务规则，Repository 负责持久化。[Spring Boot 代码结构](https://docs.spring.io/spring-boot/reference/using/structuring-your-code.html)

```text
server/src/
├── main/
│   ├── java/com/example/shop/
│   │   ├── ShopApplication.java
│   │   ├── order/
│   │   │   ├── controller/
│   │   │   ├── service/
│   │   │   ├── domain/
│   │   │   └── repository/
│   │   └── config/
│   └── resources/application.yml
└── test/java/com/example/shop/order/
```
