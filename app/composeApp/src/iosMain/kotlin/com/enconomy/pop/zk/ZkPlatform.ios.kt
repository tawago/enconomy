@file:OptIn(ExperimentalForeignApi::class, BetaInteropApi::class)

package com.enconomy.pop.zk

import kotlinx.cinterop.BetaInteropApi
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.alloc
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.ptr
import kotlinx.cinterop.reinterpret
import kotlinx.cinterop.sizeOf
import kotlinx.cinterop.usePinned
import kotlinx.cinterop.value
import com.enconomy.pop.zk.mem.pop_avail_mem
import platform.CoreFoundation.CFRelease
import platform.Foundation.NSApplicationSupportDirectory
import platform.Foundation.NSData
import platform.Foundation.NSFileHandle
import platform.Foundation.NSFileManager
import platform.Foundation.NSFileSize
import platform.Foundation.NSNumber
import platform.Foundation.NSProcessInfo
import platform.Foundation.NSURL
import platform.Foundation.NSURLIsExcludedFromBackupKey
import platform.Foundation.NSUserDomainMask
import platform.Foundation.closeFile
import platform.Foundation.create
import platform.Foundation.dataWithContentsOfFile
import platform.Foundation.fileHandleForWritingAtPath
import platform.Foundation.seekToEndOfFile
import platform.Foundation.writeData
import platform.Foundation.writeToFile
import platform.SystemConfiguration.SCNetworkReachabilityCreateWithName
import platform.SystemConfiguration.SCNetworkReachabilityFlagsVar
import platform.SystemConfiguration.SCNetworkReachabilityGetFlags
import platform.SystemConfiguration.kSCNetworkReachabilityFlagsIsWWAN
import platform.SystemConfiguration.kSCNetworkReachabilityFlagsReachable
import platform.darwin.KERN_SUCCESS
import platform.darwin.TASK_VM_INFO
import platform.darwin.integer_tVar
import platform.darwin.mach_msg_type_number_tVar
import platform.darwin.mach_task_self_
import platform.darwin.task_info
import platform.darwin.task_vm_info_data_t
import platform.posix.memcpy

actual object ZkFiles {
    private val fm get() = NSFileManager.defaultManager

    actual fun dir(): String {
        val base = fm.URLsForDirectory(NSApplicationSupportDirectory, NSUserDomainMask).first() as NSURL
        val d = base.URLByAppendingPathComponent("zk")!!
        fm.createDirectoryAtURL(d, true, null, null)
        d.setResourceValue(NSNumber(bool = true), NSURLIsExcludedFromBackupKey, null)
        return d.path!!
    }

    actual fun size(path: String): Long {
        if (!fm.fileExistsAtPath(path)) return -1
        return (fm.attributesOfItemAtPath(path, null)?.get(NSFileSize) as? NSNumber)?.longLongValue ?: -1
    }

    actual fun append(path: String, bytes: ByteArray) {
        if (!fm.fileExistsAtPath(path)) fm.createFileAtPath(path, null, null)
        val h = NSFileHandle.fileHandleForWritingAtPath(path) ?: error("cannot open $path")
        h.seekToEndOfFile()
        h.writeData(bytes.toNSData())
        h.closeFile()
    }

    actual fun write(path: String, bytes: ByteArray) {
        check(bytes.toNSData().writeToFile(path, true)) { "cannot write $path" }
    }

    actual fun read(path: String): ByteArray {
        val d = NSData.dataWithContentsOfFile(path) ?: error("cannot read $path")
        val n = d.length.toInt()
        val out = ByteArray(n)
        if (n > 0) out.usePinned { memcpy(it.addressOf(0), d.bytes, d.length) }
        return out
    }

    actual fun rename(from: String, to: String): Boolean {
        if (fm.fileExistsAtPath(to)) fm.removeItemAtPath(to, null)
        return fm.moveItemAtPath(from, to, null)
    }

    actual fun delete(path: String) { fm.removeItemAtPath(path, null) }

    private fun ByteArray.toNSData(): NSData =
        if (isEmpty()) NSData() else usePinned { NSData.create(bytes = it.addressOf(0), length = size.toULong()) }
}

actual object DeviceMemory {
    /** Simulator reports 0 (no jetsam limit) -> null. */
    actual fun info(): MemInfo {
        val avail = pop_avail_mem().toLong().takeIf { it > 0 }
        return MemInfo(NSProcessInfo.processInfo.physicalMemory.toLong(), avail, hardLimit = avail != null, usedBytes = footprint())
    }

    actual fun footprint(): Long = vm()?.first ?: 0L
    actual fun peak(): Long? = vm()?.second
    actual fun resetPeak() {}
    actual fun nativeHeap(): Long? = null

    /** (phys_footprint, ledger_phys_footprint_peak) of this task. */
    private fun vm(): Pair<Long, Long>? = memScoped {
        val info = alloc<task_vm_info_data_t>()
        val count = alloc<mach_msg_type_number_tVar>()
        count.value = (sizeOf<task_vm_info_data_t>() / sizeOf<integer_tVar>()).toUInt()
        val kr = task_info(mach_task_self_, TASK_VM_INFO.toUInt(), info.ptr.reinterpret(), count.ptr)
        if (kr != KERN_SUCCESS) null else info.phys_footprint.toLong() to info.ledger_phys_footprint_peak.toLong()
    }
}

actual fun networkIsMetered(): Boolean? = memScoped {
    val r = SCNetworkReachabilityCreateWithName(null, "apple.com") ?: return@memScoped null
    try {
        val flags = alloc<SCNetworkReachabilityFlagsVar>()
        if (!SCNetworkReachabilityGetFlags(r, flags.ptr)) return@memScoped null
        val f = flags.value
        if (f and kSCNetworkReachabilityFlagsReachable == 0u) null else (f and kSCNetworkReachabilityFlagsIsWWAN) != 0u
    } finally {
        CFRelease(r)
    }
}
