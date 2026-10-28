import { createRouter, createWebHashHistory } from 'vue-router';

// hash 路由：后端只需托管一个 index.html 入口，无 history 回退问题
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: () => import('@/features/home/HomePage.vue') },
    { path: '/shouxi', component: () => import('@/features/shouxi/ShouxiPage.vue') },
    { path: '/bigly', component: () => import('@/features/bigly/BiglyPage.vue') },
    { path: '/screener', component: () => import('@/features/screener/ScreenerPage.vue') },
    { path: '/setup', component: () => import('@/features/setup/SetupPage.vue') },
  ],
});

export default router;
