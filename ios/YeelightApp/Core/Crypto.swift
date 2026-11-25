import Foundation
import CommonCrypto

/// MD5 + AES-128-CBC/PKCS#7 lewat CommonCrypto (setara _aes.py).
enum Crypto {
    static func md5(_ data: Data) -> Data {
        var digest = [UInt8](repeating: 0, count: Int(CC_MD5_DIGEST_LENGTH))
        data.withUnsafeBytes { raw in
            _ = CC_MD5(raw.baseAddress, CC_LONG(data.count), &digest)
        }
        return Data(digest)
    }

    static func aesCBC(_ data: Data, key: Data, iv: Data, decrypt: Bool) -> Data? {
        var output = [UInt8](repeating: 0, count: data.count + kCCBlockSizeAES128)
        var written = 0
        let status = data.withUnsafeBytes { dataBytes in
            key.withUnsafeBytes { keyBytes in
                iv.withUnsafeBytes { ivBytes in
                    CCCrypt(
                        CCOperation(decrypt ? kCCDecrypt : kCCEncrypt),
                        CCAlgorithm(kCCAlgorithmAES),
                        CCOptions(kCCOptionPKCS7Padding),
                        keyBytes.baseAddress, key.count,
                        ivBytes.baseAddress,
                        dataBytes.baseAddress, data.count,
                        &output, output.count,
                        &written
                    )
                }
            }
        }
        guard status == kCCSuccess else { return nil }
        return Data(output.prefix(written))
    }
}
