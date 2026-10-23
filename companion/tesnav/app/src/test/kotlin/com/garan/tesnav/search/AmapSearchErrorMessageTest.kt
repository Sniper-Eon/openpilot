package com.garan.tesnav.search

import org.junit.Assert.assertEquals
import org.junit.Test

class AmapSearchErrorMessageTest {
    @Test
    fun `search errors distinguish credential rate-limit and network failures`() {
        assertEquals("高德 API Key、签名或平台配置错误（1008）", AmapSearchErrorMessage.forCode(1008))
        assertEquals("高德地址服务请求过于频繁（1005）", AmapSearchErrorMessage.forCode(1005))
        assertEquals("高德地址服务网络异常（1806）", AmapSearchErrorMessage.forCode(1806))
        assertEquals("高德地址服务失败（1999）", AmapSearchErrorMessage.forCode(1999))
    }
}
