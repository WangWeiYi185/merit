# 微信原生小程序目录规范

页面的逻辑、配置、模板和样式按页面放在一起。应用配置与应用入口位于实际的小程序源码根目录。下面选择 `miniprogram/` 作为源码根，项目采用其他路径时，以开发者工具的项目配置为准。[微信小程序示例工程](https://github.com/wechat-miniprogram/miniprogram-demo)

```text
mini-program/
├── project.config.json
└── miniprogram/
    ├── app.js
    ├── app.json                  # 全局配置和页面注册
    ├── app.wxss
    ├── pages/
    │   └── checkout/
    │       ├── index.js
    │       ├── index.json
    │       ├── index.wxml
    │       └── index.wxss
    ├── components/               # 跨页面复用的组件
    └── api/
        └── order.js
```
