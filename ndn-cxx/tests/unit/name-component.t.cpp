/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/*
 * Copyright (c) 2013-2024 Regents of the University of California.
 *
 * This file is part of ndn-cxx library (NDN C++ library with eXperimental eXtensions).
 *
 * ndn-cxx library is free software: you can redistribute it and/or modify it under the
 * terms of the GNU Lesser General Public License as published by the Free Software
 * Foundation, either version 3 of the License, or (at your option) any later version.
 *
 * ndn-cxx library is distributed in the hope that it will be useful, but WITHOUT ANY
 * WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
 * PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more details.
 *
 * You should have received copies of the GNU General Public License and GNU Lesser
 * General Public License along with ndn-cxx, e.g., in COPYING.md file.  If not, see
 * <http://www.gnu.org/licenses/>.
 *
 * See AUTHORS.md for complete list of ndn-cxx authors and contributors.
 */

#include "ndn-cxx/name-component.hpp"
#include "ndn-cxx/name.hpp"
#include "ndn-cxx/util/string-helper.hpp"

#include "tests/boost-test.hpp"

#include <boost/algorithm/string/case_conv.hpp>
#include <boost/algorithm/string/predicate.hpp>
#include <boost/lexical_cast.hpp>
#include <boost/mp11/list.hpp>

namespace ndn::tests {

using ndn::name::Component;
using ndn::name::UriFormat;

static_assert(sizeof(Component) == sizeof(Block));
BOOST_CONCEPT_ASSERT((boost::EqualityComparable<Component>));
BOOST_CONCEPT_ASSERT((boost::Comparable<Component>));
BOOST_CONCEPT_ASSERT((WireEncodable<Component>));
BOOST_CONCEPT_ASSERT((WireEncodableWithEncodingBuffer<Component>));
BOOST_CONCEPT_ASSERT((WireDecodable<Component>));
static_assert(std::is_convertible_v<Component::Error*, tlv::Error*>,
              "name::Component::Error must inherit from tlv::Error");

BOOST_AUTO_TEST_SUITE(TestNameComponent)

BOOST_AUTO_TEST_SUITE(Decode)

#define CHECK_COMP_ERR(expr, whatstring) \
  BOOST_CHECK_EXCEPTION(expr, Component::Error, \
                        [] (const auto& e) { return boost::contains(e.what(), whatstring); })

BOOST_AUTO_TEST_CASE(Generic)
{
  Component comp("0807 6E646E2D637878"_block);
  BOOST_CHECK_EQUAL(comp.type(), tlv::GenericNameComponent);
  BOOST_CHECK_EQUAL(comp.isGeneric(), true);
  BOOST_CHECK_EQUAL(comp.toUri(), "ndn-cxx");
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::CANONICAL), "8=ndn-cxx");
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::ALTERNATE), "ndn-cxx");
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::ENV_OR_CANONICAL), "8=ndn-cxx");
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::ENV_OR_ALTERNATE), "ndn-cxx");
  BOOST_CHECK_EQUAL(boost::lexical_cast<std::string>(comp), "ndn-cxx");
  BOOST_CHECK_EQUAL(Component::fromUri("ndn-cxx"), comp);
  BOOST_CHECK_EQUAL(Component::fromUri("8=ndn-cxx"sv), comp);

  comp.wireDecode("0800"_block);
  BOOST_CHECK_EQUAL(comp.toUri(), "...");
  BOOST_CHECK_EQUAL(Component::fromUri("..."), comp);
  BOOST_CHECK_EQUAL(Component::fromUri("8=..."sv), comp);
  BOOST_CHECK_EQUAL(Component::fromUri(".%2E."sv), comp);

  comp.wireDecode("0801 2E"_block);
  BOOST_CHECK_EQUAL(comp.toUri(), "....");
  BOOST_CHECK_EQUAL(Component::fromUri("...."), comp);
  BOOST_CHECK_EQUAL(Component::fromUri("%2E..%2E"sv), comp);

  comp.wireDecode("0803 2E412E"_block);
  BOOST_CHECK_EQUAL(comp.toUri(), ".A.");
  BOOST_CHECK_EQUAL(Component::fromUri(".A."sv), comp);

  comp.wireDecode("0807 666F6F25626172"_block);
  BOOST_CHECK_EQUAL(comp.toUri(), "foo%25bar");
  BOOST_CHECK_EQUAL(Component::fromUri("foo%25bar"), comp);
  BOOST_CHECK_EQUAL(Component::fromUri("8=foo%25bar"sv), comp);

  comp.wireDecode("0804 2D2E5F7E"_block);
  BOOST_CHECK_EQUAL(comp.toUri(), "-._~");
  BOOST_CHECK_EQUAL(Component::fromUri("-._~"sv), comp);

  comp.wireDecode("0803 393D41"_block);
  BOOST_CHECK_EQUAL(comp.toUri(), "9%3DA");
  BOOST_CHECK_EQUAL(Component::fromUri("9%3DA"sv), comp);

  comp = Component(":/?#[]@");
  BOOST_CHECK_EQUAL(comp.toUri(), "%3A%2F%3F%23%5B%5D%40");
  BOOST_CHECK_EQUAL(Component::fromUri("%3A%2F%3F%23%5B%5D%40"sv), comp);

  BOOST_CHECK_THROW(Component::fromUri(""), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri(""sv), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("."sv), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri(".."sv), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("8="sv), Component::Error);
}

static void
testSha256Component(uint32_t type, const std::string& uriPrefix)
{
  const std::string hexLower = "28bad4b5275bd392dbb670c75cf0b66f13f7942b21e80f55c0e86b374753a548";
  const std::string hexUpper = boost::to_upper_copy(hexLower);
  std::string hexPct;
  for (size_t i = 0; i < hexUpper.size(); i += 2) {
    hexPct += "%" + hexUpper.substr(i, 2);
  }
  const std::string hexPctCanonical = "%28%BA%D4%B5%27%5B%D3%92%DB%B6p%C7%5C%F0%B6o%13%F7%94%2B%21%E8%0FU%C0%E8k7GS%A5H";

  Component comp(type, fromHex(hexLower));

  BOOST_CHECK_EQUAL(comp.type(), type);
  BOOST_CHECK_EQUAL(comp.toUri(), uriPrefix + hexLower);
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::CANONICAL), std::to_string(type) + "=" + hexPctCanonical);
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::ALTERNATE), uriPrefix + hexLower);
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::ENV_OR_CANONICAL), std::to_string(type) + "=" + hexPctCanonical);
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::ENV_OR_ALTERNATE), uriPrefix + hexLower);
  BOOST_CHECK_EQUAL(boost::lexical_cast<std::string>(comp), uriPrefix + hexLower);
  BOOST_CHECK_EQUAL(comp, Component::fromUri(uriPrefix + hexLower));
  BOOST_CHECK_EQUAL(comp, Component::fromUri(uriPrefix + hexUpper));
  BOOST_CHECK_EQUAL(comp, Component::fromUri(std::to_string(type) + "=" + hexPct));
  BOOST_CHECK_EQUAL(comp, Component::fromUri(std::to_string(type) + "=" + hexPctCanonical));

  CHECK_COMP_ERR(comp.wireDecode(Block(type, fromHex("A791806951F25C4D"))), "TLV-LENGTH must be 32");
  CHECK_COMP_ERR(Component::fromUri(uriPrefix), "TLV-LENGTH must be 32");
  CHECK_COMP_ERR(Component::fromUri(uriPrefix + "a791806951f25c4d"), "TLV-LENGTH must be 32");
  CHECK_COMP_ERR(Component::fromUri(uriPrefix + "foo"), "invalid hex encoding");
  CHECK_COMP_ERR(Component::fromUri(boost::to_upper_copy(uriPrefix) + hexLower), "Unknown TLV-TYPE");
}

BOOST_AUTO_TEST_CASE(ImplicitDigest)
{
  testSha256Component(tlv::ImplicitSha256DigestComponent, "sha256digest=");
}

BOOST_AUTO_TEST_CASE(ParametersDigest)
{
  testSha256Component(tlv::ParametersSha256DigestComponent, "params-sha256=");
}

static void
testDecimalComponent(uint32_t type, const std::string& uriPrefix)
{
  const Component comp(makeNonNegativeIntegerBlock(type, 42)); // TLV-VALUE is a NonNegativeInteger
  BOOST_CHECK_EQUAL(comp.type(), type);
  BOOST_CHECK_EQUAL(comp.isNumber(), true);
  const auto compUri = uriPrefix + "42";
  BOOST_CHECK_EQUAL(comp.toUri(), compUri);
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::CANONICAL), std::to_string(type) + "=%2A");
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::ALTERNATE), compUri);
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::ENV_OR_CANONICAL), std::to_string(type) + "=%2A");
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::ENV_OR_ALTERNATE), compUri);
  BOOST_CHECK_EQUAL(boost::lexical_cast<std::string>(comp), compUri);
  BOOST_CHECK_EQUAL(comp, Component::fromUri(compUri));
  BOOST_CHECK_EQUAL(comp, Component::fromUri(std::to_string(type) + "=%2A"));
  BOOST_CHECK_EQUAL(comp, Component::fromNumber(42, type));

  const Component comp2(type, fromHex("010203")); // TLV-VALUE is *not* a NonNegativeInteger
  BOOST_CHECK_EQUAL(comp2.type(), type);
  BOOST_CHECK_EQUAL(comp2.isNumber(), false);
  const auto comp2Uri = std::to_string(type) + "=%01%02%03";
  BOOST_CHECK_EQUAL(comp2.toUri(), comp2Uri);
  BOOST_CHECK_EQUAL(boost::lexical_cast<std::string>(comp2), comp2Uri);
  BOOST_CHECK_EQUAL(comp2, Component::fromUri(comp2Uri));

  CHECK_COMP_ERR(Component::fromUri(uriPrefix), "invalid format");
  CHECK_COMP_ERR(Component::fromUri(uriPrefix + "foo"), "invalid format");
  CHECK_COMP_ERR(Component::fromUri(uriPrefix + "00"), "invalid format");
  CHECK_COMP_ERR(Component::fromUri(uriPrefix + "-1"), "invalid format");
  CHECK_COMP_ERR(Component::fromUri(uriPrefix + "9.3"), "invalid format");
  CHECK_COMP_ERR(Component::fromUri(uriPrefix + " 84"), "invalid format");
  CHECK_COMP_ERR(Component::fromUri(uriPrefix + "0xAF"), "invalid format");
  CHECK_COMP_ERR(Component::fromUri(uriPrefix + "18446744073709551616"), "out of range");
  CHECK_COMP_ERR(Component::fromUri(boost::to_upper_copy(uriPrefix) + "42"), "Unknown TLV-TYPE");
}

BOOST_AUTO_TEST_CASE(Segment)
{
  testDecimalComponent(tlv::SegmentNameComponent, "seg=");
}

BOOST_AUTO_TEST_CASE(ByteOffset)
{
  testDecimalComponent(tlv::ByteOffsetNameComponent, "off=");
}

BOOST_AUTO_TEST_CASE(Version)
{
  testDecimalComponent(tlv::VersionNameComponent, "v=");
}

BOOST_AUTO_TEST_CASE(Timestamp)
{
  testDecimalComponent(tlv::TimestampNameComponent, "t=");
}

BOOST_AUTO_TEST_CASE(SequenceNum)
{
  testDecimalComponent(tlv::SequenceNumNameComponent, "seq=");
}

BOOST_AUTO_TEST_CASE(Keyword)
{
  Component comp("2007 6E646E2D637878"_block);
  BOOST_CHECK_EQUAL(comp.type(), tlv::KeywordNameComponent);
  BOOST_CHECK_EQUAL(comp.isKeyword(), true);
  BOOST_CHECK_EQUAL(comp.toUri(), "32=ndn-cxx");
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::CANONICAL), "32=ndn-cxx");
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::ALTERNATE), "32=ndn-cxx");
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::ENV_OR_CANONICAL), "32=ndn-cxx");
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::ENV_OR_ALTERNATE), "32=ndn-cxx");
  BOOST_CHECK_EQUAL(Component::fromUri("32=ndn-cxx"sv), comp);

  comp.wireDecode("2000"_block);
  BOOST_CHECK_EQUAL(comp.type(), tlv::KeywordNameComponent);
  BOOST_CHECK_EQUAL(comp.isKeyword(), true);
  BOOST_CHECK_EQUAL(comp.toUri(), "32=...");
  BOOST_CHECK_EQUAL(Component::fromUri("32=..."sv), comp);

  BOOST_CHECK_THROW(Component::fromUri("32="sv), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("32=."sv), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("32=.."sv), Component::Error);
}

BOOST_AUTO_TEST_CASE(OtherType)
{
  Component comp("0907 6E646E2D637878"_block);
  BOOST_CHECK_EQUAL(comp.type(), 0x09);
  BOOST_CHECK_EQUAL(comp.toUri(), "9=ndn-cxx");
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::CANONICAL), "9=ndn-cxx");
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::ALTERNATE), "9=ndn-cxx");
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::ENV_OR_CANONICAL), "9=ndn-cxx");
  BOOST_CHECK_EQUAL(comp.toUri(UriFormat::ENV_OR_ALTERNATE), "9=ndn-cxx");
  BOOST_CHECK_EQUAL(Component::fromUri("9=ndn-cxx"sv), comp);

  comp.wireDecode("FDFFFF00"_block);
  BOOST_CHECK_EQUAL(comp.type(), 0xFFFF);
  BOOST_CHECK_EQUAL(comp.toUri(), "65535=...");
  BOOST_CHECK_EQUAL(Component::fromUri("65535=..."sv), comp);

  comp.wireDecode("FD576501 2E"_block);
  BOOST_CHECK_EQUAL(comp.type(), 0x5765);
  BOOST_CHECK_EQUAL(comp.toUri(), "22373=....");
  BOOST_CHECK_EQUAL(Component::fromUri("22373=...."sv), comp);

  BOOST_CHECK_THROW(Component::fromUri("3="sv), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("3=."sv), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("3=.."sv), Component::Error);
}

BOOST_AUTO_TEST_CASE(InvalidType)
{
  Component comp;
  BOOST_CHECK_THROW(comp.wireDecode(Block{}), Component::Error);
  BOOST_CHECK_THROW(comp.wireDecode("FE0001000001 80"_block), Component::Error);

  BOOST_CHECK_THROW(Component::fromUri("0=A"), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("65536=A"), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("4294967296=A"), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("-1=A"), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("+=A"), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("=A"), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("0x1=A"), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("Z=A"), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("09=A"), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("0x3=A"), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("+9=A"), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri(" 9=A"), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("9 =A"), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("9.0=A"), Component::Error);
  BOOST_CHECK_THROW(Component::fromUri("9E0=A"), Component::Error);
}

BOOST_AUTO_TEST_SUITE_END() // Decode

BOOST_AUTO_TEST_CASE(ConstructFromSpan)
{
  const uint8_t arr[] = {1, 2, 3};
  Component c1(arr);
  BOOST_TEST(c1.wireEncode() == "0803010203"_block);
  Component c2(128, arr);
  BOOST_TEST(c2.wireEncode() == "8003010203"_block);

  const std::vector<uint8_t> vec = {4, 5, 6};
  Component c3(vec);
  BOOST_TEST(c3.wireEncode() == "0803040506"_block);
  Component c4(128, vec);
  BOOST_TEST(c4.wireEncode() == "8003040506"_block);

  Component c5(128, {7, 8});
  BOOST_TEST(c5.wireEncode() == "80020708"_block);

  const Block b("090109"_block);
  Component c6(128, b);
  BOOST_TEST(c6.wireEncode() == "8003090109"_block);
}

BOOST_AUTO_TEST_SUITE(ConstructFromIterators) // Bug 2490

using ContainerTypes = boost::mp11::mp_list<
  std::vector<uint8_t>,
  std::list<uint8_t>,
  std::vector<int8_t>,
  std::list<int8_t>
>;

BOOST_AUTO_TEST_CASE_TEMPLATE(ZeroOctets, T, ContainerTypes)
{
  T bytes;
  Component c(bytes.begin(), bytes.end());
  BOOST_TEST(c.type() == tlv::GenericNameComponent);
  BOOST_TEST(c.value_size() == 0);
  BOOST_TEST(c.size() == 2);
}

BOOST_AUTO_TEST_CASE_TEMPLATE(OneOctet, T, ContainerTypes)
{
  T bytes{1};
  Component c(9, bytes.begin(), bytes.end());
  BOOST_TEST(c.type() == 0x09);
  BOOST_TEST(c.value_size() == 1);
  BOOST_TEST(c.size() == 3);
}

BOOST_AUTO_TEST_CASE_TEMPLATE(FourOctets, T, ContainerTypes)
{
  T bytes{1, 2, 3, 4};
  Component c(0xFCEC, bytes.begin(), bytes.end());
  BOOST_TEST(c.type() == 0xFCEC);
  BOOST_TEST(c.value_size() == 4);
  BOOST_TEST(c.size() == 8);
}

BOOST_AUTO_TEST_SUITE_END() // ConstructFromIterators

template<typename ArgType>
struct ConventionTest
{
  std::function<Component(ArgType)> makeComponent;
  std::function<ArgType(const Component&)> getValue;
  std::function<Name&(Name&, ArgType)> append;
  Name expected;
  ArgType value;
  std::function<bool(const Component&)> isComponent;
};

struct ConventionMarker
{
  ConventionMarker()
  {
    name::setConventionEncoding(name::Convention::MARKER);
  }

  ~ConventionMarker()
  {
    name::setConventionEncoding(name::Convention::TYPED);
  }
};

struct ConventionTyped
{
};

struct NumberWithMarker
{
  using ConventionRev = ConventionMarker;

  ConventionTest<uint64_t>
  operator()() const
  {
    return {[] (auto num) { return Component::fromNumberWithMarker(0xAA, num); },
            [] (const Component& c) { return c.toNumberWithMarker(0xAA); },
            [] (Name& name, auto num) -> Name& { return name.appendNumberWithMarker(0xAA, num); },
            Name("/%AA%03%E8"),
            1000,
            [] (const Component& c) { return c.isNumberWithMarker(0xAA); }};
  }
};

struct SegmentMarker
{
  using ConventionRev = ConventionMarker;

  ConventionTest<uint64_t>
  operator()() const
  {
    return {&Component::fromSegment,
            &Component::toSegment,
            &Name::appendSegment,
            Name("/%00%27%10"),
            10000,
            &Component::isSegment};
  }
};

struct SegmentTyped
{
  using ConventionRev = ConventionTyped;

  ConventionTest<uint64_t>
  operator()() const
  {
    return {&Component::fromSegment,
            &Component::toSegment,
            &Name::appendSegment,
            Name("/50=%27%10"),
            10000,
            &Component::isSegment};
  }
};

struct ByteOffsetTyped
{
  using ConventionRev = ConventionTyped;

  ConventionTest<uint64_t>
  operator()() const
  {
    return {&Component::fromByteOffset,
            &Component::toByteOffset,
            &Name::appendByteOffset,
            Name("/52=%00%01%86%A0"),
            100000,
            &Component::isByteOffset};
  }
};

struct VersionMarker
{
  using ConventionRev = ConventionMarker;

  ConventionTest<uint64_t>
  operator()() const
  {
    return {&Component::fromVersion,
            &Component::toVersion,
            [] (Name& name, auto version) -> Name& { return name.appendVersion(version); },
            Name("/%FD%00%0FB%40"),
            1000000,
            &Component::isVersion};
  }
};

struct VersionTyped
{
  using ConventionRev = ConventionTyped;

  ConventionTest<uint64_t>
  operator()() const
  {
    return {&Component::fromVersion,
            &Component::toVersion,
            [] (Name& name, auto version) -> Name& { return name.appendVersion(version); },
            Name("/54=%00%0FB%40"),
            1000000,
            &Component::isVersion};
  }
};

struct TimestampMarker
{
  using ConventionRev = ConventionMarker;

  ConventionTest<time::system_clock::time_point>
  operator()() const
  {
    return {&Component::fromTimestamp,
            &Component::toTimestamp,
            [] (Name& name, auto tp) -> Name& { return name.appendTimestamp(tp); },
            Name("/%FC%00%04%7BE%E3%1B%00%00"),
            time::getUnixEpoch() + 14600_days, // 40 years
            &Component::isTimestamp};
  }
};

struct TimestampTyped
{
  using ConventionRev = ConventionTyped;

  ConventionTest<time::system_clock::time_point>
  operator()() const
  {
    return {&Component::fromTimestamp,
            &Component::toTimestamp,
            [] (Name& name, auto tp) -> Name& { return name.appendTimestamp(tp); },
            Name("/56=%00%04%7BE%E3%1B%00%00"),
            time::getUnixEpoch() + 14600_days, // 40 years
            &Component::isTimestamp};
  }
};

struct SequenceNumberMarker
{
  using ConventionRev = ConventionMarker;

  ConventionTest<uint64_t>
  operator()() const
  {
    return {&Component::fromSequenceNumber,
            &Component::toSequenceNumber,
            &Name::appendSequenceNumber,
            Name("/%FE%00%98%96%80"),
            10000000,
            &Component::isSequenceNumber};
  }
};

struct SequenceNumberTyped
{
  using ConventionRev = ConventionTyped;

  ConventionTest<uint64_t>
  operator()() const
  {
    return {&Component::fromSequenceNumber,
            &Component::toSequenceNumber,
            &Name::appendSequenceNumber,
            Name("/58=%00%98%96%80"),
            10000000,
            &Component::isSequenceNumber};
  }
};

using NamingConventionTests = boost::mp11::mp_list<
  NumberWithMarker,
  SegmentMarker,
  SegmentTyped,
  ByteOffsetTyped,
  VersionMarker,
  VersionTyped,
  TimestampMarker,
  TimestampTyped,
  SequenceNumberMarker,
  SequenceNumberTyped
>;

BOOST_FIXTURE_TEST_CASE_TEMPLATE(NamingConvention, T, NamingConventionTests, T::ConventionRev)
{
  auto test = T()();

  Component actualComponent = test.makeComponent(test.value);
  BOOST_CHECK_EQUAL(actualComponent, test.expected[0]);

  Name actualName;
  test.append(actualName, test.value);
  BOOST_CHECK_EQUAL(actualName, test.expected);

  BOOST_CHECK_EQUAL(test.isComponent(test.expected[0]), true);
  BOOST_CHECK_EQUAL(test.getValue(test.expected[0]), test.value);

  static const Component invalidComponent1;
  static const Component invalidComponent2("1234567890");

  BOOST_CHECK_EQUAL(test.isComponent(invalidComponent1), false);
  BOOST_CHECK_EQUAL(test.isComponent(invalidComponent2), false);

  BOOST_CHECK_THROW(test.getValue(invalidComponent1), Component::Error);
  BOOST_CHECK_THROW(test.getValue(invalidComponent2), Component::Error);
}

BOOST_AUTO_TEST_CASE(Compare)
{
  const std::vector<Component> comps = {
    Component("0120 0000000000000000000000000000000000000000000000000000000000000000"_block),
    Component("0120 0000000000000000000000000000000000000000000000000000000000000001"_block),
    Component("0120 FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF"_block),
    Component("0220 0000000000000000000000000000000000000000000000000000000000000000"_block),
    Component("0220 0000000000000000000000000000000000000000000000000000000000000001"_block),
    Component("0220 FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF"_block),
    Component(0x03),
    Component("0301 44"_block),
    Component("0301 46"_block),
    Component("0302 4141"_block),
    Component(),
    Component("D"),
    Component("F"),
    Component("AA"),
    Component(0x53B2),
    Component("FD53B201 44"_block),
    Component("FD53B201 46"_block),
    Component("FD53B202 4141"_block),
  };

  for (size_t i = 0; i < comps.size(); ++i) {
    for (size_t j = 0; j < comps.size(); ++j) {
      const auto& lhs = comps[i];
      const auto& rhs = comps[j];
      BOOST_TEST_INFO_SCOPE("lhs = " << lhs);
      BOOST_TEST_INFO_SCOPE("rhs = " << rhs);
      BOOST_CHECK_EQUAL(lhs == rhs, i == j);
      BOOST_CHECK_EQUAL(lhs != rhs, i != j);
      BOOST_CHECK_EQUAL(lhs <  rhs, i <  j);
      BOOST_CHECK_EQUAL(lhs <= rhs, i <= j);
      BOOST_CHECK_EQUAL(lhs >  rhs, i >  j);
      BOOST_CHECK_EQUAL(lhs >= rhs, i >= j);
    }
  }
}

BOOST_AUTO_TEST_SUITE_END() // TestNameComponent

} // namespace ndn::tests
