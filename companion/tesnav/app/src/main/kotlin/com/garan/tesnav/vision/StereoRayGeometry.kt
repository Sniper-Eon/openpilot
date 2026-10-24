package com.garan.tesnav.vision

import kotlin.math.*

/** Camera-coordinate geometry only; all inputs must first be undistorted. */
internal object StereoRayGeometry {
    fun dot(a: DoubleArray,b: DoubleArray)=a.indices.sumOf { a[it]*b[it] }
    fun mul(r: List<Double>,a: DoubleArray)=DoubleArray(3) { i -> (0..2).sumOf { j -> r[i*3+j]*a[j] } }
    fun transpose(r: List<Double>)=List(9) { r[(it%3)*3+it/3] }
    private fun unit(x: Double,y: Double): DoubleArray {
        val n=sqrt(x*x+y*y+1);return doubleArrayOf(x/n,y/n,1/n)
    }
    fun point(wx: Double,wy: Double,nx: Double,ny: Double,r: List<Double>,t: List<Double>): DoubleArray? {
        if(r.size!=9 || t.size!=3 || (r+t+listOf(wx,wy,nx,ny)).any { !it.isFinite() }) return null
        val a=unit(wx,wy);val rt=transpose(r);val b=mul(rt,unit(nx,ny));val c=mul(rt,t.toDoubleArray()).map { -it }.toDoubleArray()
        val d=dot(a,b);val den=1-d*d
        if(den<=1e-12) return null
        val ac=dot(a,c);val bc=dot(b,c);val s=(ac-d*bc)/den;val q=(d*ac-bc)/den
        if(s<=0 || q<=0) return null
        val p=DoubleArray(3) { a[it]*s };val other=DoubleArray(3) { c[it]+b[it]*q }
        val gap=sqrt((0..2).sumOf { (p[it]-other[it]).pow(2) })
        val result=DoubleArray(3) { (p[it]+other[it])/2 }
        return result.takeIf { it.all { v -> v.isFinite() } && it[2] in 2.0..80.0 && gap<=max(.01,it[2]*.002) }
    }
    fun reliable(base: DoubleArray, shifted: List<DoubleArray?>, baseline: Double, skewNs: Long): Boolean {
        if(baseline !in .01..0.5 || abs(skewNs)>5_000_000 || shifted.size!=8 || shifted.any { it==null }) return false
        val spatial=shifted.maxOf { abs(it!![2]-base[2]) }
        val timing=base[2]*40.0*abs(skewNs)/1e9/baseline
        return spatial+timing<=max(.25,base[2]*.2)
    }
    fun roadPoint(widePoint: DoubleArray,r: List<Double>,t: List<Double>,narrowViewFromCalib: List<Double>?): GroundPoint? {
        if(narrowViewFromCalib?.size!=12 || narrowViewFromCalib.any { !it.isFinite() }) return null
        for(i in 0..2)for(j in 0..2)if(abs((0..2).sumOf { k -> narrowViewFromCalib[k*4+i]*narrowViewFromCalib[k*4+j] }-(if(i==j)1.0 else 0.0))>1e-4)return null
        if(abs(narrowViewFromCalib[3])>1e-6 || abs(narrowViewFromCalib[11])>1e-6 || narrowViewFromCalib[7] !in .5..3.0)return null
        val n=mul(r,widePoint);for(i in 0..2)n[i]+=t[i]-narrowViewFromCalib[i*4+3]
        val result=DoubleArray(3) { col -> (0..2).sumOf { row -> narrowViewFromCalib[row*4+col]*n[row] } }
        return GroundPoint(result[0],result[1]).takeIf { result.all { v -> v.isFinite() } && it.forward in 2.0..80.0 && abs(it.lateral)<=25 && result[2] in -5.0..1.0 }
    }
}
