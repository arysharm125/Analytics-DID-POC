import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import vuetify from './plugins/vuetify'
import { FontAwesomeIcon } from './plugins/font-awesome'
import '@fortawesome/fontawesome-free/css/all.min.css'

// Import global styles
import './style.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(vuetify)
app.component('font-awesome-icon', FontAwesomeIcon)

app.mount('#app')
