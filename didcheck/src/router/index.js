import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '@/views/HomeView.vue'
import IdentifierCheck from '@/views/IdentifierCheck.vue'
import VCValidationView from '@/views/VCValidationView.vue'

const routes = [
  {
    path: '/',
    name: 'home',
    component: HomeView
  },
  {
    path: '/validate-vc/:validationId',
    name: 'validate-vc',
    component: VCValidationView,
    props: true
  },
  {
    path: '/did/:identifier',
    name: 'identifier-check',
    component: IdentifierCheck,
    props: true
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

export default router
